from fastapi import FastAPI, Request, Response, status
from app.config import GITHUB_WEBHOOK_SECRET
from app.queue import get_redis
from app.github.validator import verify_signature
from app.database.postgres import get_connection
from app.database.repository import (
    register_webhook_delivery,
    claim_review,
    claim_review_run,
    get_review,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)

app = FastAPI(title="AI Pull Request Review Agent")


@app.get("/")
async def root():
    return {
        "status": "running",
        "project": "AI Pull Request Review Agent",
    }


@app.get("/health")
async def health():
    """Liveness probe — returns status ok."""
    return {"status": "ok"}


@app.get("/ready")
async def ready(response: Response):
    """
    Readiness probe — checks connectivity to PostgreSQL and Redis.
    Does NOT call external Gemini or GitHub APIs.
    """
    db_ok = False
    redis_ok = False

    # Check PostgreSQL
    try:
        conn = get_connection()
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
        conn.close()
        db_ok = True
    except Exception as exc:
        logger.error("[Ready Check] PostgreSQL ping failed: %s", exc)

    # Check Redis
    try:
        redis = await get_redis()
        pong = await redis.ping()
        redis_ok = bool(pong)
    except Exception as exc:
        logger.error("[Ready Check] Redis ping failed: %s", exc)

    if db_ok and redis_ok:
        return {
            "status": "ready",
            "postgres": "ok",
            "redis": "ok",
        }

    response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {
        "status": "not_ready",
        "postgres": "ok" if db_ok else "failed",
        "redis": "ok" if redis_ok else "failed",
    }


@app.post("/webhook")
async def webhook(request: Request):

    # 1. Read raw request body
    body = await request.body()

    # 2. Verify GitHub signature
    signature = request.headers.get("X-Hub-Signature-256")
    verify_signature(
        payload=body,
        signature=signature,
        secret=GITHUB_WEBHOOK_SECRET,
    )

    # 3. Get GitHub delivery ID
    delivery_id = request.headers.get("X-GitHub-Delivery")
    if not delivery_id:
        return {
            "status": "ignored",
            "reason": "missing delivery ID",
        }

    # 4. Parse payload
    payload = await request.json()
    event_type = request.headers.get("X-GitHub-Event")
    action = payload.get("action")

    logger.info("GitHub Event: %s, Action: %s, Delivery ID: %s", event_type, action, delivery_id)

    # 5. Webhook delivery idempotency
    is_new_delivery = register_webhook_delivery(
        delivery_id=delivery_id,
        event_type=event_type,
        action=action,
    )

    if not is_new_delivery:
        logger.info("Duplicate webhook ignored: %s", delivery_id)
        return {
            "status": "ignored",
            "reason": "duplicate delivery",
        }

    # 6. Only process pull_request
    if event_type != "pull_request":
        return {
            "status": "ignored",
            "reason": f"event={event_type}",
        }

    # 7. Only process relevant actions
    if action not in {"opened", "synchronize", "reopened"}:
        return {
            "status": "ignored",
            "reason": f"action={action}",
        }

    # 8. Extract PR information
    pull_request = payload["pull_request"]
    repository = payload["repository"]
    installation = payload["installation"]

    pr_number = pull_request["number"]
    commit_sha = pull_request["head"]["sha"]
    repository_name = repository["full_name"]
    owner = repository["owner"]["login"]
    repo = repository["name"]
    installation_id = installation["id"]

    logger.info("Processing PR #%d on %s (SHA: %s)", pr_number, repository_name, commit_sha[:8])

    # 9. Claim review in review_runs & legacy reviews table
    claim_res = claim_review_run(
        installation_id=installation_id,
        owner=owner,
        repo=repo,
        pr_number=pr_number,
        commit_sha=commit_sha,
    )

    # Keep legacy reviews table updated for backward compatibility
    claim_review(
        repository=repository_name,
        pr_number=pr_number,
        commit_sha=commit_sha,
    )

    if not claim_res.claimed:
        logger.info(
            "Review claim skipped (%s): %s:%d:%s",
            claim_res.reason, repository_name, pr_number, commit_sha[:8]
        )
        return {
            "status": "ignored",
            "reason": f"review_{claim_res.reason}",
            "review_id": claim_res.review_id,
        }

    review_id = claim_res.review_id

    # 10. Queue review job in ARQ
    redis = await get_redis()
    job = await redis.enqueue_job(
        "review_pr",
        installation_id=installation_id,
        owner=owner,
        repo=repo,
        pr_number=pr_number,
        repository=repository_name,
        commit_sha=commit_sha,
        review_id=review_id,
    )

    logger.info("Review job %s queued for PR #%d (review_id: %s)", job.job_id, pr_number, review_id)

    return {
        "status": "queued",
        "pr": pr_number,
        "commit_sha": commit_sha,
        "review_id": review_id,
        "job_id": job.job_id,
    }


@app.get("/reviews/{repository:path}/{pr_number}/{commit_sha}")
async def review_status(
    repository: str,
    pr_number: int,
    commit_sha: str,
):
    review = get_review(
        repository=repository,
        pr_number=pr_number,
        commit_sha=commit_sha,
    )

    if not review:
        return {
            "status": "not_found",
            "message": "Review not found",
        }

    return review