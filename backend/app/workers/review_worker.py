from arq.connections import RedisSettings

from app.database.repository import (
    update_review_status,
    complete_review,
    fail_review,
)
from app.services.review_service import review_pull_request


async def review_pr(
    ctx,
    installation_id: int,
    owner: str,
    repo: str,
    pr_number: int,
    repository: str,
    commit_sha: str,
):
    print("\n========== WORKER ==========")

    print(f"Reviewing PR #{pr_number}")
    print(f"Repository: {repository}")
    print(f"Commit SHA: {commit_sha}")

    # --------------------------------
    # Mark review as PROCESSING
    # --------------------------------

    update_review_status(
        repository=repository,
        pr_number=pr_number,
        commit_sha=commit_sha,
        status="PROCESSING",
    )

    try:
        # --------------------------------
        # Run existing AI review
        # --------------------------------

        review, decision = review_pull_request(
            installation_id=installation_id,
            owner=owner,
            repo=repo,
            pr_number=pr_number,
        )

        # --------------------------------
        # Convert findings to JSON-safe data
        # --------------------------------

        findings = []

        for finding in review.findings:
            if hasattr(finding, "model_dump"):
                findings.append(finding.model_dump())
            elif hasattr(finding, "dict"):
                findings.append(finding.dict())
            else:
                findings.append(finding)

        # --------------------------------
        # Save successful result
        # --------------------------------

        complete_review(
            repository=repository,
            pr_number=pr_number,
            commit_sha=commit_sha,
            decision=decision,
            findings=findings,
        )

        print(f"Review completed: {decision}")

        return {
            "status": "completed",
            "decision": decision,
            "findings": len(review.findings),
        }

    except Exception as e:
        # --------------------------------
        # Save failed result
        # --------------------------------

        print(f"Review failed: {e}")

        fail_review(
            repository=repository,
            pr_number=pr_number,
            commit_sha=commit_sha,
            error_message=str(e),
        )

        raise


class WorkerSettings:
    functions = [
        review_pr,
    ]

    redis_settings = RedisSettings(
        host="127.0.0.1",
        port=6379,
    )