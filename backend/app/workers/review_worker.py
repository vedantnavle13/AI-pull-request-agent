from arq.connections import RedisSettings

from app.github.auth import get_installation_token
from app.github.client import GitHubClient
from app.github.review import build_review_comments

from app.database.repository import (
    claim_review,
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

    print(
        f"Reviewing PR #{pr_number}"
    )

    print(
        f"Repository: {repository}"
    )

    print(
        f"Commit SHA: {commit_sha}"
    )

    try:

        # ==================================
        # 1. CLAIM REVIEW
        # ==================================

        claimed = claim_review(
            repository=repository,
            pr_number=pr_number,
            commit_sha=commit_sha,
        )

        if not claimed:

            print(
                "Review already claimed or processed:"
                f" {repository}:{pr_number}:{commit_sha}"
            )

            return {
                "status": "skipped",
                "reason": "review_already_claimed",
            }

        # ==================================
        # 2. GET INSTALLATION TOKEN
        # ==================================

        print(
            "Generating GitHub installation token..."
        )

        github_token = get_installation_token(
            installation_id
        )

        print(
            "GitHub installation token obtained."
        )

        # ==================================
        # 3. RUN AI REVIEW
        # ==================================

        print(
            "Running AI review..."
        )

        review, decision = review_pull_request(
            installation_id=installation_id,
            owner=owner,
            repo=repo,
            pr_number=pr_number,
        )

        print(
            f"Policy decision: {decision}"
        )

        # ==================================
        # 4. CONVERT FINDINGS TO DICT
        # ==================================

        findings = []

        for finding in review.findings:

            if hasattr(
                finding,
                "model_dump",
            ):

                findings.append(
                    finding.model_dump()
                )

            elif hasattr(
                finding,
                "dict",
            ):

                findings.append(
                    finding.dict()
                )

            else:

                findings.append(
                    finding
                )

        print(
            f"Findings: {len(findings)}"
        )

        # ==================================
        # 5. BUILD GITHUB COMMENTS
        # ==================================

        comments = build_review_comments(
            findings
        )

        print(
            f"GitHub comments: {len(comments)}"
        )

        # ==================================
        # 6. CREATE GITHUB CLIENT
        # ==================================

        github = GitHubClient(
            token=github_token
        )

        # ==================================
        # 7. SELECT GITHUB REVIEW EVENT
        # ==================================

        if decision == "APPROVE":

            event = "APPROVE"

        else:

            # HUMAN_REVIEW_REQUIRED
            # and other non-approve decisions
            # are posted as comments for now.

            event = "COMMENT"

        # ==================================
        # 8. SUBMIT REVIEW TO GITHUB
        # ==================================

        print(
            "Submitting review to GitHub..."
        )

        github_review = (
            github.submit_pull_request_review(
                owner=owner,
                repo=repo,
                pr_number=pr_number,
                commit_sha=commit_sha,
                body=(
                    "🤖 AI Code Review\n\n"
                    f"Decision: {decision}"
                ),
                event=event,
                comments=comments,
            )
        )

        github_review_id = github_review.get(
            "id"
        )

        print(
            f"GitHub review created: "
            f"{github_review_id}"
        )

        # ==================================
        # 9. SAVE SUCCESSFUL REVIEW
        # ==================================

        complete_review(
            repository=repository,
            pr_number=pr_number,
            commit_sha=commit_sha,
            decision=decision,
            findings=findings,
            github_review_id=github_review_id,
        )

        print(
            "Review successfully completed."
        )

        return {
            "status": "completed",
            "decision": decision,
            "findings": len(findings),
            "github_review_id": github_review_id,
        }

    except Exception as e:

        # ==================================
        # 10. SAVE FAILURE
        # ==================================

        print(
            f"Review failed: {e}"
        )

        fail_review(
            repository=repository,
            pr_number=pr_number,
            commit_sha=commit_sha,
            error_message=str(e),
        )

        # Re-raise so ARQ can retry.
        raise


class WorkerSettings:

    functions = [
        review_pr,
    ]

    max_tries = 3

    redis_settings = RedisSettings(
        host="127.0.0.1",
        port=6379,
    )