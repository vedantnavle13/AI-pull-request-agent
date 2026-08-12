"""
Phase 10, 11, 12, 13 & 14 — Hardened Review Worker with Full Observability.

Pipeline:
    1.  claim_review_run() / start_review()
    2.  get_installation_token()
    3.  Fetch PR diff + files from GitHub
    4.  PRCheckout (checkout HEAD in isolated directory)
    5.  TestRunner (run tests with secret environment stripping and timeouts)
    6.  Build LangGraph state & invoke graph (4 agents, aggregator, validator, evidence, decision)
    7.  Record real LLM token usage per-agent from graph result state
    8.  Record per-agent timing metrics (concurrent — NOT summed)
    9.  Record duration metrics in review_metrics table
    10. Publish review via ReviewPublisher (summary + inline comments with 422 fallback)
    11. Phase 13: Auto-Merge Gate
    12. Phase 14: Structured logs at every stage; error_metric on failure
    13. Transition review_runs status -> COMPLETED (or DEAD_LETTER if max retries exceeded)
    14. PRCheckout.cleanup()
"""

import time
import logging
import os
from datetime import datetime, timezone

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
    claim_merge,
    create_merge_record,
    record_merge_result,
    record_agent_metrics,
    record_error_metric,
)
from app.services.auto_merge import evaluate_auto_merge_gate
from app.config import AUTO_MERGE_ENABLED, AUTO_MERGE_METHOD, AUTO_MERGE_REQUIRE_CHECKS
from app.github.client import (
    GitHubAPIError,
    GitHubRateLimitError,
    GitHubServerError,
    GitHubValidationError,
)
from app.utils.cost import calculate_llm_cost

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

    logger.info("========== WORKER (Phase 12-14) ==========")
    logger.info(
        "[Stage:RECEIVED] review_id=%s repo=%s pr=%d sha=%s",
        review_id, repository, pr_number, commit_sha[:8]
    )

    ensure_schema()
    pipeline_start = time.perf_counter()
    pipeline_start_utc = datetime.now(timezone.utc)

    # 1. Claim Review Run
    claim = claim_review_run(
        installation_id=installation_id,
        owner=owner,
        repo=repo,
        pr_number=pr_number,
        commit_sha=commit_sha,
    )

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
        logger.info(
            "[Stage:CLAIMED] review_id=%s repo=%s pr=%d sha=%s",
            active_review_id, repository, pr_number, commit_sha[:8],
        )
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
        logger.info("[Stage:CHECKOUT_START] review_id=%s pr=%d", active_review_id, pr_number)
        checkout_result = checkout.checkout(owner=owner, repo=repo, pr_number=pr_number, token=github_token)
        checkout_path = checkout_result.path if checkout_result.success else None
        t_checkout_dur = int((time.perf_counter() - t_checkout_start) * 1000)
        logger.info(
            "[Stage:CHECKOUT_DONE] review_id=%s pr=%d duration_ms=%d success=%s",
            active_review_id, pr_number, t_checkout_dur, checkout_result.success,
        )

        # 5. Run Isolated Tests
        t_test_start = time.perf_counter()
        test_result_dicts: list[dict] = []
        if checkout_path:
            logger.info("[Stage:TESTS_START] review_id=%s pr=%d", active_review_id, pr_number)
            runner = TestRunner(timeout=TEST_TIMEOUT_SECONDS)
            test_res = runner.run_python_tests(checkout_path)
            test_result_dicts = [test_res.model_dump()]
        else:
            test_result_dicts = [{"status": "NOT_RUN", "failure_summary": []}]
        t_test_dur = int((time.perf_counter() - t_test_start) * 1000)
        logger.info(
            "[Stage:TESTS_DONE] review_id=%s pr=%d duration_ms=%d",
            active_review_id, pr_number, t_test_dur,
        )

        # 6. Execute LangGraph Review Pipeline
        update_review_run_status(active_review_id, "AI_REVIEWING")
        t_agent_start = time.perf_counter()
        logger.info("[Stage:AGENTS_START] review_id=%s pr=%d", active_review_id, pr_number)

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

        result = await graph.ainvoke(graph_state)
        t_agent_dur = int((time.perf_counter() - t_agent_start) * 1000)

        logger.info(
            "[Stage:AGENTS_DONE] review_id=%s pr=%d wall_clock_ms=%d",
            active_review_id, pr_number, t_agent_dur,
        )

        update_review_run_status(active_review_id, "VALIDATING")
        findings = result.get("findings", [])
        decision = result.get("decision", "HUMAN_REVIEW")
        validation_errors = result.get("validation_errors", [])
        final_test_results = result.get("test_results", test_result_dicts)

        # --- Per-agent metrics (real, concurrent timings from graph state) ---
        _agent_ts_to_dt = lambda ts: (
            datetime.fromtimestamp(ts, tz=timezone.utc) if ts else None
        )
        for ag_name, ag_prefix in [
            ("security", "security"),
            ("quality",  "quality"),
            ("tests",    "tests"),
            ("docs",     "docs"),
        ]:
            ag_dur  = result.get(f"{ag_prefix}_duration_ms")
            ag_ok   = result.get(f"{ag_prefix}_success", True)
            ag_t0   = result.get(f"{ag_prefix}_started_at")
            ag_t1   = result.get(f"{ag_prefix}_completed_at")
            # finding counts per agent from their individual findings lists
            ag_findings_key = (
                "security_findings" if ag_name == "security" else
                "quality_findings"  if ag_name == "quality"  else
                "test_findings"     if ag_name == "tests"    else
                "docs_findings"
            )
            ag_finding_count = len(result.get(ag_findings_key, []))

            record_agent_metrics(
                review_id=active_review_id,
                agent_name=ag_name,
                started_at=_agent_ts_to_dt(ag_t0),
                completed_at=_agent_ts_to_dt(ag_t1),
                duration_ms=ag_dur,
                success=ag_ok,
                finding_count=ag_finding_count,
            )

        # --- Real LLM token usage per-agent ---
        model_name = os.getenv("GEMINI_MODEL", "gemini-flash-latest")
        for ag_name, ag_prefix in [
            ("security", "security"),
            ("quality",  "quality"),
            ("tests",    "tests"),
            ("docs",     "docs"),
        ]:
            usage = result.get(f"{ag_prefix}_usage") or {}
            input_tok  = usage.get("input_tokens")
            output_tok = usage.get("output_tokens")
            total_tok  = usage.get("total_tokens")
            model_used = usage.get("model") or model_name
            cost = calculate_llm_cost(
                model=model_used,
                input_tokens=input_tok,
                output_tokens=output_tok,
            )
            record_llm_usage(
                review_id=active_review_id,
                agent=ag_name,
                model=model_used,
                input_tokens=input_tok,
                output_tokens=output_tok,
                total_tokens=total_tok,
                estimated_cost=cost,
            )
            logger.info(
                "[LLM:%s] review_id=%s tokens=(%s,%s,%s) cost=%s",
                ag_name, active_review_id, input_tok, output_tok, total_tok, cost,
            )

        # 7. Persist Result to Database
        update_review_run_status(active_review_id, "POLICY_DECISION")
        logger.info(
            "[Stage:POLICY] review_id=%s pr=%d decision=%s findings=%d",
            active_review_id, pr_number, decision, len(findings),
        )
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
        logger.info("[Stage:PUBLISH_START] review_id=%s pr=%d", active_review_id, pr_number)
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
        logger.info(
            "[Stage:PUBLISH_DONE] review_id=%s pr=%d duration_ms=%d inline=%s",
            active_review_id, pr_number, t_pub_dur,
            pub_result.get("inline_count", 0),
        )

        total_dur = int((time.perf_counter() - pipeline_start) * 1000)
        # queue_wait = time from webhook queuing to worker start
        queue_wait_ms = int((time.perf_counter() - pipeline_start) * 1000 - t_checkout_dur - t_test_dur - t_agent_dur - t_pub_dur)
        record_review_metrics(
            review_id=active_review_id,
            total_duration_ms=total_dur,
            queue_wait_ms=max(0, queue_wait_ms),
            checkout_duration_ms=t_checkout_dur,
            agent_duration_ms=t_agent_dur,
            test_duration_ms=t_test_dur,
            publishing_duration_ms=t_pub_dur,
            final_decision=decision,
            final_status="COMPLETED",
        )

        update_review_run_status(active_review_id, "COMPLETED")
        logger.info(
            "[Stage:COMPLETED] review_id=%s repo=%s pr=%d decision=%s total_ms=%d",
            active_review_id, repository, pr_number, decision, total_dur,
        )

        # ----------------------------------------------------------------
        # 9. Phase 13 — Auto-Merge Gate
        # ----------------------------------------------------------------
        merge_result_data = {"merge_status": "NOT_ELIGIBLE", "merge_commit_sha": None}

        if AUTO_MERGE_ENABLED:
            logger.info("[AutoMerge] Evaluating gates for PR #%d", pr_number)

            gate = evaluate_auto_merge_gate(
                decision=decision,
                validation_errors=validation_errors,
                findings=findings,
                test_results=final_test_results,
                review_status="COMPLETED",
                auto_merge_enabled=AUTO_MERGE_ENABLED,
                auto_merge_require_checks=AUTO_MERGE_REQUIRE_CHECKS,
                github=github,
                owner=owner,
                repo=repo,
                pr_number=pr_number,
                reviewed_sha=commit_sha,
            )

            # Create audit record in all cases
            initial_merge_status = "ELIGIBLE" if gate.allowed else "NOT_ELIGIBLE"
            create_merge_record(
                review_id=active_review_id,
                repository=repository,
                pr_number=pr_number,
                reviewed_sha=commit_sha,
                decision=decision,
                merge_status=initial_merge_status,
                merge_method=AUTO_MERGE_METHOD if gate.allowed else None,
            )

            if not gate.allowed:
                logger.info(
                    "[AutoMerge] Gate DENIED for PR #%d: %s (gate=%s)",
                    pr_number, gate.reason, gate.gate_failed,
                )
                record_merge_result(
                    active_review_id,
                    "NOT_ELIGIBLE",
                    current_sha=gate.current_sha or None,
                    checks_status=gate.checks_status,
                    error=gate.reason,
                )
            else:
                # Atomically claim merge attempt
                merge_claimed = claim_merge(active_review_id)

                if not merge_claimed:
                    logger.warning(
                        "[AutoMerge] PR #%d merge already claimed by another worker",
                        pr_number,
                    )
                else:
                    try:
                        logger.info(
                            "[AutoMerge] Merging PR #%d SHA=%s method=%s",
                            pr_number, commit_sha[:8], AUTO_MERGE_METHOD,
                        )
                        merge_response = github.merge_pull_request(
                            owner=owner,
                            repo=repo,
                            pr_number=pr_number,
                            expected_sha=commit_sha,
                            merge_method=AUTO_MERGE_METHOD,
                            commit_title=f"Auto-merge PR #{pr_number}: {pub_result.get('pr_title', '')}",
                        )
                        merge_commit_sha = merge_response.get("sha", "")
                        logger.info(
                            "[AutoMerge] MERGED PR #%d → commit %s",
                            pr_number, merge_commit_sha[:8] if merge_commit_sha else "?",
                        )
                        record_merge_result(
                            active_review_id,
                            "MERGED",
                            current_sha=commit_sha,
                            merge_commit_sha=merge_commit_sha,
                            checks_status=gate.checks_status,
                        )
                        merge_result_data = {
                            "merge_status": "MERGED",
                            "merge_commit_sha": merge_commit_sha,
                        }

                    except GitHubAPIError as merge_err:
                        status_code = merge_err.status_code

                        # HEAD changed during the merge window → ABORTED
                        if status_code == 409:
                            logger.warning(
                                "[AutoMerge] ABORTED PR #%d — HEAD changed during merge: %s",
                                pr_number, merge_err,
                            )
                            record_merge_result(
                                active_review_id, "ABORTED",
                                error=str(merge_err), checks_status=gate.checks_status,
                            )

                        # Transient errors (rate-limit, server errors) → FAILED + re-raise
                        elif isinstance(merge_err, (GitHubRateLimitError, GitHubServerError)):
                            logger.error(
                                "[AutoMerge] Transient error for PR #%d (status=%d), will retry: %s",
                                pr_number, status_code, merge_err,
                            )
                            record_merge_result(
                                active_review_id, "FAILED",
                                error=str(merge_err), checks_status=gate.checks_status,
                            )
                            # Do NOT raise — review pipeline itself succeeded.
                            # Merge will be retried on next run if needed.

                        # Non-retryable (401, 403, 405, 422) → FAILED, do not retry
                        else:
                            logger.error(
                                "[AutoMerge] Non-retryable merge failure for PR #%d (status=%d): %s",
                                pr_number, status_code, merge_err,
                            )
                            record_merge_result(
                                active_review_id, "FAILED",
                                error=str(merge_err), checks_status=gate.checks_status,
                            )
        else:
            logger.debug("[AutoMerge] Disabled — skipping merge gate for PR #%d", pr_number)

        return {
            "status": "completed",
            "decision": decision,
            "findings": len(findings),
            "inline_comments": pub_result.get("inline_count", 0),
            "github_review_id": pub_result.get("github_review_id"),
            "review_id": active_review_id,
            "auto_merge": merge_result_data,
        }

    except Exception as e:
        logger.error(
            "[Stage:FAILED] review_id=%s repo=%s pr=%d error=%s",
            active_review_id, repository, pr_number, type(e).__name__, exc_info=True,
        )

        # Always mark FAILED immediately so ARQ retry / next webhook can reclaim.
        attempt = ctx.get("job_try", 1) if isinstance(ctx, dict) else 1

        # Categorize error for observability
        err_name = type(e).__name__
        if "GitHub" in err_name and "RateLimit" in err_name:
            err_category = "GITHUB_RATE_LIMIT"
        elif "GitHub" in err_name:
            err_category = "GITHUB_API"
        elif "Gemini" in err_name or "API" in err_name:
            err_category = "GEMINI_API"
        elif "Checkout" in err_name or "checkout" in str(e).lower():
            err_category = "CHECKOUT"
        elif "Test" in err_name:
            err_category = "TEST_EXECUTION"
        elif "Database" in err_name or "psycopg" in err_name:
            err_category = "DATABASE"
        else:
            err_category = "UNKNOWN"

        try:
            record_error_metric(
                stage="REVIEW_PIPELINE",
                error_category=err_category,
                review_id=active_review_id,
                error_type=err_name,
                error_message=str(e)[:500],
                retryable=(attempt < MAX_REVIEW_RETRIES),
                attempt=attempt,
            )
        except Exception:
            pass  # Never let observability break the error path

        if active_review_id:
            if attempt >= MAX_REVIEW_RETRIES:
                logger.error(
                    "[Worker] Review reached MAX_RETRIES (%d). Moving to DEAD_LETTER.",
                    MAX_REVIEW_RETRIES,
                )
                update_review_run_status(
                    active_review_id, "DEAD_LETTER",
                    error_type=type(e).__name__, error_message=str(e),
                )
            else:
                update_review_run_status(
                    active_review_id, "FAILED",
                    error_type=type(e).__name__, error_message=str(e),
                )

        # Also update legacy reviews table so claim_review() sees FAILED → retriable.
        fail_review(
            repository=repository,
            pr_number=pr_number,
            commit_sha=commit_sha,
            error_message=str(e),
        )

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