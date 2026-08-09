from app.config import GITHUB_WEBHOOK_SECRET

from app.github.validator import verify_signature

from app.services.review_service import review_pull_request

from app.database.repository import (
    already_reviewed,
    create_review_event,
    register_webhook_delivery,
)


from fastapi import FastAPI, Request


app = FastAPI()


@app.get("/")
async def root():

    return {
        "status": "running",
        "project": "AI Pull Request Review Agent",
    }


@app.post("/webhook")
async def webhook(request: Request):

    # --------------------------------
    # 1. Read raw request body
    # --------------------------------

    body = await request.body()

    # --------------------------------
    # 2. Verify GitHub signature
    # --------------------------------

    signature = request.headers.get(
        "X-Hub-Signature-256"
    )

    verify_signature(
        payload=body,
        signature=signature,
        secret=GITHUB_WEBHOOK_SECRET,
    )

    # --------------------------------
    # 3. Get delivery ID
    # --------------------------------

    delivery_id = request.headers.get(
        "X-GitHub-Delivery"
    )

    if not delivery_id:

        return {
            "status": "ignored",
            "reason": "missing delivery ID",
        }

 
    # --------------------------------
    # 5. Parse payload
    # --------------------------------

    payload = await request.json()

    event_type = request.headers.get(
        "X-GitHub-Event"
    )

    action = payload.get("action")



    print(
        f"GitHub Event: {event_type}"
    )

    print(
        f"Action: {action}"
    )

    is_new_delivery = register_webhook_delivery(
    delivery_id=delivery_id,
    event_type=event_type,
    action=action,
    )

    if not is_new_delivery:

        print(
        f"Duplicate webhook ignored: {delivery_id}"
    )

    return {
        "status": "ignored",
        "reason": "duplicate delivery",
    }

    # --------------------------------
    # 6. Only process pull_request
    # --------------------------------

    if event_type != "pull_request":

        return {
            "status": "ignored",
            "reason": f"event={event_type}",
        }

    # --------------------------------
    # 7. Only process relevant actions
    # --------------------------------

    if action not in {
        "opened",
        "synchronize",
        "reopened",
    }:

        return {
            "status": "ignored",
            "reason": f"action={action}",
        }

    # --------------------------------
    # 8. Extract PR information
    # --------------------------------

    pull_request = payload["pull_request"]

    repository = payload["repository"]

    installation = payload["installation"]

    pr_number = pull_request["number"]

    commit_sha = pull_request["head"]["sha"]

    repository_name = repository["full_name"]

    owner = repository["owner"]["login"]

    repo = repository["name"]

    installation_id = installation["id"]

    print(
        f"Reviewing PR #{pr_number}"
    )

    print(
        f"Repository: {owner}/{repo}"
    )

    print(
        f"Commit SHA: {commit_sha}"
    )

    # --------------------------------
    # 9. PostgreSQL review idempotency
    # --------------------------------

    if already_reviewed(
        repository=repository_name,
        pr_number=pr_number,
        commit_sha=commit_sha,
    ):

        print(
            "Duplicate review ignored: "
            f"{repository_name}:{pr_number}:{commit_sha}"
        )

        return {
            "status": "ignored",
            "reason": "PR commit already reviewed",
        }

    # --------------------------------
    # 10. Run AI review
    # --------------------------------

    review, decision = review_pull_request(
        installation_id=installation_id,
        owner=owner,
        repo=repo,
        pr_number=pr_number,
    )

    # --------------------------------
    # 11. Save successful review
    # --------------------------------

    create_review_event(
        repository=repository_name,
        pr_number=pr_number,
        commit_sha=commit_sha,
        status="completed",
        decision=decision,
    )

    # --------------------------------
    # 12. Print AI findings
    # --------------------------------

    print(
        "\n========== AI REVIEW ==========\n"
    )

    for finding in review.findings:

        print(
            "Severity:",
            finding.severity,
        )

        print(
            "Category:",
            finding.category,
        )

        print(
            "File:",
            finding.file,
        )

        print(
            "Line:",
            finding.line,
        )

        print(
            "Title:",
            finding.title,
        )

        print(
            "Description:",
            finding.description,
        )

        print(
            "Suggestion:",
            finding.suggestion,
        )

    print(
        "Decision:",
        decision,
    )

    # --------------------------------
    # 13. Response
    # --------------------------------

    return {
        "status": "review_completed",
        "pr": pr_number,
        "findings": len(review.findings),
        "decision": decision,
    }