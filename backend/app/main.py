from app.config import GITHUB_WEBHOOK_SECRET
import requests
import jwt
from app.github.client import GitHubClient
from app.github.validator import verify_signature

# pyrefly: ignore [missing-import]
from fastapi import FastAPI, Request

from app.services.review_service import review_pull_request


from app.services.idempotency import (
    already_processed,
    mark_processed,
)

app = FastAPI()


@app.get("/")
async def root():
    return {
        "status": "running",
        "project": "AI Pull Request Review Agent"
    }


@app.post("/webhook")
async def webhook(request: Request):

    body = await request.body()
    signature = request.headers.get(
        "X-Hub-Signature-256"
    )
    verify_signature(
        payload=body,
        signature=signature,
        secret=GITHUB_WEBHOOK_SECRET,
    )
   
    delivery_id = request.headers.get(
        "X-GitHub-Delivery"
    )

    if not delivery_id:
        return {
            "status": "ignored",
            "reason": "missing delivery ID",
        }

    if already_processed(delivery_id):

        print(
            f"Duplicate webhook ignored: {delivery_id}"
        )

        return {
            "status": "ignored",
            "reason": "duplicate delivery",
        }

    mark_processed(delivery_id)
    print(f"Processing webhook: {delivery_id}")

    payload = await request.json()

    action = payload.get("action")

    # We only care about newly opened PRs for now
    if action != "opened":
        return {
            "status": "ignored",
            "reason": f"action={action}"
        }

    pull_request = payload["pull_request"]
    repository = payload["repository"]
    installation = payload["installation"]

    owner = repository["owner"]["login"]
    repo = repository["name"]

    pr_number = pull_request["number"]
    installation_id = installation["id"]

    print(f"Reviewing PR #{pr_number}")
    print(f"Repository: {owner}/{repo}")

    review,decision = review_pull_request(
        installation_id=installation_id,
        owner=owner,
        repo=repo,
        pr_number=pr_number,
    )


    print("\n========== AI REVIEW ==========\n")

    for finding in review.findings:

        print("Severity:", finding.severity)
        print("Category:", finding.category)
        print("File:", finding.file)
        print("Line:", finding.line)
        print("Title:", finding.title)
        print("Description:", finding.description)
        print("Suggestion:", finding.suggestion)
        print("decision:", decision)

    return {
        "status": "review_completed",
        "pr": pr_number,
        "findings": len(review.findings),
        "decision": decision,
    }