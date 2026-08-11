from fastapi import FastAPI, Request

from app.config import GITHUB_WEBHOOK_SECRET
from app.queue import get_redis

from app.github.validator import verify_signature

from app.database.repository import (
    register_webhook_delivery,
    claim_review,
)


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
    # 3. Get GitHub delivery ID
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
    # 4. Parse payload
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

    print(
        f"Delivery ID: {delivery_id}"
    )

    # --------------------------------
    # 5. Webhook delivery idempotency
    # --------------------------------

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
    # 9. Claim review in PostgreSQL
    # --------------------------------
    #
    # This atomically checks whether
    # this exact PR + commit has already
    # been queued/reviewed.
    #
    # If it already exists:
    #     claim_review() -> False
    #
    # If it is new:
    #     claim_review() -> True
    #
    # --------------------------------

    claimed = claim_review(
        repository=repository_name,
        pr_number=pr_number,
        commit_sha=commit_sha,
    )

    if not claimed:

        print(
            "Review already queued or processed:"
            f" {repository_name}:{pr_number}:{commit_sha}"
        )

        return {
            "status": "ignored",
            "reason": "review already queued or processed",
        }

    # --------------------------------
    # 10. Get Redis connection
    # --------------------------------

    redis = await get_redis()

    # --------------------------------
    # 11. Queue review job
    # --------------------------------

    job = await redis.enqueue_job(
        "review_pr",
        installation_id=installation_id,
        owner=owner,
        repo=repo,
        pr_number=pr_number,
        repository=repository_name,
        commit_sha=commit_sha,
    )

    print(
        f"Review queued for PR #{pr_number}"
    )

    print(
        f"Job ID: {job.job_id}"
    )

    # --------------------------------
    # 12. Return immediately
    # --------------------------------

    return {
        "status": "queued",
        "pr": pr_number,
        "commit_sha": commit_sha,
        "job_id": job.job_id,
    }