"""
Phase 10, 11 & Phase 12 — Hardened Review Worker with Full State Machine.

Pipeline:
    1.  claim_review_run() / start_review()
    2.  get_installation_token()
    3.  Fetch PR diff + files from GitHub
    4.  PRCheckout (checkout HEAD in isolated directory)
    5.  TestRunner (run tests with secret environment stripping and timeouts)
    6.  Build LangGraph state & invoke graph (4 agents, aggregator, validator, evidence, decision)
    7.  Record LLM token usage in llm_usage table
    8.  Record duration metrics in review_metrics table
    9.  Publish review via ReviewPublisher (summary + inline comments with 422 fallback)
    10. Transition review_runs status -> COMPLETED (or DEAD_LETTER if max retries exceeded)
    11. PRCheckout.cleanup()
"""

import time
import logging

import app.config  # noqa: F401
from langsmith import traceable
from arq.connections import RedisSettings

from app.config import MAX_REVIEW_RETRIES, TEST_TIMEOUT_SECONDS
from app.github.auth import get_installation_token
from app.github.client import GitHubClient
from app.github.diff import extract_diff
from app.github.review import ReviewPublisher

from app.database.migrations import ensure_schema
from app.database.repository import (
    start_review,
    complete_review,
    fail_review,
    claim_review_run,
    update_review_run_status,
    record_llm_usage,
    record_review_metrics,
)

from app.orchestrator.graph import build_review_graph
from app.services.repo_checkout import PRCheckout
from app.services.test_runner import TestRunner
from app.utils.logger import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Worker function
# ---------------------------------------------------------------------------

async def review_pr(
    ctx,
    installation_id: int,
    owner: str,
    repo: str,
    pr_number: int,
    repository: str,
    commit_sha: str,
    review_id: str | None = None,
    **kwargs,
):

    """
    ARQ task — reviews a single PR.
    Wrapped in a LangSmith root trace so the entire pipeline appears as one trace.
    """

    @traceable(
        run_type="chain",
        name=f"review_pr:{repository}#{pr_number}",
        tags=["arq", "pr-review", repository],
        metadata={
            "repository": repository,
            "pr_number": pr_number,
            "commit_sha": commit_sha,
            "review_id": review_id,
        },
    )
    async def _run():
        return await _review_pr_impl(
            ctx=ctx,
            installation_id=installation_id,
            owner=owner,
            repo=repo,
            pr_number=pr_number,
            repository=repository,
            commit_sha=commit_sha,
            review_id=review_id,
        )

    return await _run()


async def _review_pr_impl(
    ctx,
    installation_id: int,
    owner: str,
    repo: str,
    pr_number: int,
    repository: str,
    commit_sha: str,
    review_id: str | None = None,
    **kwargs,
):

    logger.info("========== WORKER (Phase 12) ==========")
    logger.info("Reviewing PR #%d on %s (SHA: %s, review_id: %s)", pr_number, repository, commit_sha[:8], review_id)

    ensure_schema()
    pipeline_start = time.perf_counter()

    # 1. Claim Review Run
    claim = claim_review_run(
        installation_id=installation_id,
        owner=owner,
        repo=repo,
        pr_number=pr_number,
        commit_sha=commit_sha,
    )

    start_review(repository=repository, pr_number=pr_number, commit_sha=commit_sha)

    if not claim.claimed:
        logger.info("[Worker] Skipping — review run not claimable (%s)", claim.reason)
        return {
            "status": "skipped",
            "reason": f"review_{claim.reason}",
            "review_id": claim.review_id,
        }

    active_review_id = claim.review_id or review_id
    checkout = PRCheckout(timeout=120)
    checkout_path: str | None = None

    try:
        # 2. Get Installation Token & Client
        update_review_run_status(active_review_id, "PROCESSING")
        github_token = get_installation_token(installation_id)
        github = GitHubClient(token=github_token)

        # 3. Fetch PR Files & Diff
        files = github.get_pull_request_files(owner=owner, repo=repo, pr_number=pr_number)
        changes = extract_diff(files)
        diff_text = ""
        for change in changes:
            diff_text += f"\n\nFILE: {change['filename']}\n"
            diff_text += change.get("patch", "")

        # 4. Checkout PR HEAD
        t_checkout_start = time.perf_counter()
        checkout_result = checkout.checkout(owner=owner, repo=repo, pr_number=pr_number, token=github_token)
        checkout_path = checkout_result.path if checkout_result.success else None
        t_checkout_dur = int((time.perf_counter() - t_checkout_start) * 1000)

        # 5. Run Isolated Tests
        t_test_start = time.perf_counter()
        test_result_dicts: list[dict] = []
        if checkout_path:
            runner = TestRunner(timeout=TEST_TIMEOUT_SECONDS)
            test_res = runner.run_python_tests(checkout_path)
            test_result_dicts = [test_res.model_dump()]
        else:
            test_result_dicts = [{"status": "NOT_RUN", "failure_summary": []}]
        t_test_dur = int((time.perf_counter() - t_test_start) * 1000)

        # 6. Execute LangGraph Review Pipeline
        update_review_run_status(active_review_id, "AI_REVIEWING")
        t_agent_start = time.perf_counter()

        graph = build_review_graph()
        graph_state = {
            "installation_id": installation_id,
            "owner": owner,
            "repo": repo,
            "pr_number": pr_number,
            "commit_sha": commit_sha,
            "diff": diff_text,
            "files": files,
            "test_results": test_result_dicts,
            "review_id": active_review_id,
        }

        result = graph.invoke(graph_state)
        t_agent_dur = int((time.perf_counter() - t_agent_start) * 1000)

        update_review_run_status(active_review_id, "VALIDATING")
        findings = result.get("findings", [])
        decision = result.get("decision", "HUMAN_REVIEW")
        validation_errors = result.get("validation_errors", [])
        final_test_results = result.get("test_results", test_result_dicts)

        # Record LLM Usage Token Metrics
        for agent_name in ("security", "quality", "tests", "docs"):
            record_llm_usage(
                review_id=active_review_id,
                agent=agent_name,
                model=os.getenv("GEMINI_MODEL", "gemini-flash-latest"),
                input_tokens=None,
                output_tokens=None,
                total_tokens=None,
            )

        # 7. Persist Result to Database
        update_review_run_status(active_review_id, "POLICY_DECISION")
        complete_review(
            repository=repository,
            pr_number=pr_number,
            commit_sha=commit_sha,
            decision=decision,
            findings=findings,
        )

        # 8. Publish Review to GitHub
        update_review_run_status(active_review_id, "PUBLISHING")
        t_pub_start = time.perf_counter()
        publisher = ReviewPublisher()
        pub_result = publisher.publish(
            github=github,
            owner=owner,
            repo=repo,
            pr_number=pr_number,
            commit_sha=commit_sha,
            findings=findings,
            files=files,
            decision=decision,
            test_results=final_test_results,
            validation_errors=validation_errors,
            repository=repository,
        )
        t_pub_dur = int((time.perf_counter() - t_pub_start) * 1000)

        total_dur = int((time.perf_counter() - pipeline_start) * 1000)
        record_review_metrics(
            review_id=active_review_id,
            total_duration_ms=total_dur,
            checkout_duration_ms=t_checkout_dur,
            agent_duration_ms=t_agent_dur,
            test_duration_ms=t_test_dur,
            publishing_duration_ms=t_pub_dur,
        )

        update_review_run_status(active_review_id, "COMPLETED")
        logger.info("Review completed successfully for %s PR #%d", repository, pr_number)

        return {
            "status": "completed",
            "decision": decision,
            "findings": len(findings),
            "inline_comments": pub_result.get("inline_count", 0),
            "github_review_id": pub_result.get("github_review_id"),
            "review_id": active_review_id,
        }

    except Exception as e:
        logger.error("[Worker] Review failed: %s", e, exc_info=True)
        fail_review(repository=repository, pr_number=pr_number, commit_sha=commit_sha, error_message=str(e))

        # Check job job attempts from context or default
        attempt = ctx.get("job_try", 1) if isinstance(ctx, dict) else 1
        if attempt >= MAX_REVIEW_RETRIES:
            logger.error("[Worker] Review reached MAX_RETRIES (%d). Moving to DEAD_LETTER.", MAX_REVIEW_RETRIES)
            update_review_run_status(active_review_id, "DEAD_LETTER", error_type=type(e).__name__, error_message=str(e))
        else:
            update_review_run_status(active_review_id, "FAILED", error_type=type(e).__name__, error_message=str(e))

        raise e

    finally:
        if checkout_path:
            checkout.cleanup(checkout_path)


# ---------------------------------------------------------------------------
# ARQ Worker Settings & Graceful Shutdown
# ---------------------------------------------------------------------------

async def startup(ctx):
    logger.info("[Worker] ARQ worker starting up...")
    ensure_schema()


async def shutdown(ctx):
    logger.info("[Worker] ARQ worker shutting down gracefully...")


class WorkerSettings:
    functions = [review_pr]
    on_startup = startup
    on_shutdown = shutdown
    max_tries = MAX_REVIEW_RETRIES
    redis_settings = RedisSettings(host="127.0.0.1", port=6379)