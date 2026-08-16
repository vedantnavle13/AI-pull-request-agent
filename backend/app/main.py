from fastapi import FastAPI, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from app.config import GITHUB_WEBHOOK_SECRET, FRONTEND_URL
from app.queue import get_redis
from app.github.validator import verify_signature
from app.database.postgres import get_connection
from app.database.repository import (
    register_webhook_delivery,
    claim_review,
    claim_review_run,
    get_review,
    get_user_id_for_installation,
    get_installation_by_installation_id,
    upsert_repository,
    upsert_github_installation_orphan,
    deactivate_repository,
)
from app.utils.logger import get_logger
from app.api.metrics import router as metrics_router
from app.api.auth import router as auth_router
from app.github.installation_sync import sync_installation_repositories, _fetch_installation_info

logger = get_logger(__name__)

app = FastAPI(
    title="AI Pull Request Review Agent",
    description="AI-powered code review with full observability (Phase 14) + multi-user SaaS (Phase 3/4)",
    version="15.1.0",
)

# ---------------------------------------------------------------------------
# CORS — required for browser clients (frontend → backend cross-origin calls)
# Allow the FRONTEND_URL origin with credentials (for HttpOnly cookie auth).
# Never use wildcard origin with allow_credentials=True.
# ---------------------------------------------------------------------------
frontend_origin = FRONTEND_URL.rstrip("/")
cors_origins = list({
    frontend_origin,
    "https://ai-pull-request-agent.onrender.com",
    "http://localhost:3000",
    "http://localhost:5173",
    "http://127.0.0.1:3000",
})

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept"],
)

app.include_router(metrics_router, prefix="/metrics")
app.include_router(auth_router)  # Phase 3/4: auth, installation, user endpoints


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

    # 6. Process installation and repository sync events
    if event_type in ("installation", "installation_repositories"):
        installation_id = payload.get("installation", {}).get("id")
        if not installation_id:
            return {"status": "ignored", "reason": "missing installation id"}

        logger.info(
            "[Webhook] %s action=%s installation_id=%s",
            event_type, action, installation_id,
        )

        # Ensure the installation exists in our DB (create orphan if not)
        try:
            installation = get_installation_by_installation_id(installation_id)
            if not installation:
                logger.info(
                    "[Webhook] Installation %s not in DB — creating orphan record",
                    installation_id,
                )
                inst_info = _fetch_installation_info(installation_id)
                account = inst_info.get("account", {})
                installation = upsert_github_installation_orphan(
                    installation_id=installation_id,
                    account_id=account.get("id", 0),
                    account_login=account.get("login", ""),
                    account_type=account.get("type", "User"),
                )
                logger.info(
                    "[Webhook] Created orphan installation uuid=%s",
                    installation["id"],
                )
        except Exception as e:
            logger.error("[Webhook] Failed to resolve installation %s: %s", installation_id, e)
            return {"status": "error", "reason": str(e)}

        installation_uuid = installation["id"]

        if event_type == "installation_repositories":
            # GitHub sends the exact repos added/removed in the payload —
            # use that directly instead of a full API re-sync.
            repos_added   = payload.get("repositories_added", [])
            repos_removed = payload.get("repositories_removed", [])

            added_count   = 0
            removed_count = 0

            for repo in repos_added:
                try:
                    upsert_repository(
                        installation_uuid=installation_uuid,
                        github_repo_id=repo["id"],
                        owner=repo["full_name"].split("/")[0],
                        name=repo["name"],
                        full_name=repo["full_name"],
                        private=repo.get("private", False),
                        default_branch=repo.get("default_branch", "main"),
                    )
                    added_count += 1
                    logger.info("[Webhook] Added repo: %s", repo["full_name"])
                except Exception as e:
                    logger.error("[Webhook] Failed to add repo %s: %s", repo.get("full_name"), e)

            for repo in repos_removed:
                try:
                    deactivate_repository(
                        installation_uuid=installation_uuid,
                        github_repo_id=repo["id"],
                    )
                    removed_count += 1
                    logger.info("[Webhook] Removed repo: %s", repo["full_name"])
                except Exception as e:
                    logger.error("[Webhook] Failed to remove repo %s: %s", repo.get("full_name"), e)

            return {
                "status": "synced",
                "added": added_count,
                "removed": removed_count,
            }

        else:  # event_type == "installation" (full install / uninstall / suspend)
            if action == "deleted" or action == "suspend":
                # Deactivate all repos for this installation
                try:
                    conn = get_connection()
                    with conn.cursor() as cur:
                        cur.execute(
                            "UPDATE repositories SET active=FALSE, updated_at=NOW() "
                            "WHERE installation_id=%s",
                            (installation_uuid,),
                        )
                    conn.commit()
                    conn.close()
                    logger.info("[Webhook] Deactivated all repos for installation %s", installation_id)
                except Exception as e:
                    logger.error("[Webhook] Failed to deactivate repos: %s", e)
                return {"status": "deactivated"}

            # For new installs or unsuspend, do a full sync via GitHub API
            try:
                synced = sync_installation_repositories(
                    installation_id=installation_id,
                    installation_uuid=installation_uuid,
                    upsert_repo_fn=upsert_repository,
                )
                logger.info(
                    "[Webhook] Full sync: %d repos for installation_id=%s",
                    len(synced), installation_id,
                )
                return {"status": "synced", "repositories_count": len(synced)}
            except Exception as e:
                logger.error("[Webhook] Full sync failed for installation %s: %s", installation_id, e)
                return {"status": "error", "reason": str(e)}

    # 7. Only process pull_request beyond this point
    if event_type != "pull_request":
        return {
            "status": "ignored",
            "reason": f"event={event_type}",
        }

    # 8. Only process relevant PR actions
    if action not in {"opened", "synchronize", "reopened"}:
        return {
            "status": "ignored",
            "reason": f"action={action}",
        }

    # 9. Extract PR information
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

    # Phase 3 — non-blocking ownership lookup.
    # We log which user owns this installation for traceability.
    # We do NOT reject the webhook if the installation is not yet registered
    # (the installation callback may not have been processed yet).
    try:
        user_id = get_user_id_for_installation(installation_id)
        if user_id:
            logger.info(
                "[Phase3] PR #%d installation_id=%d owned by user_id=%s",
                pr_number, installation_id, user_id,
            )
        else:
            logger.info(
                "[Phase3] PR #%d installation_id=%d not yet registered in users table — "
                "proceeding without owner association",
                pr_number, installation_id,
            )
    except Exception as _lookup_exc:
        logger.warning(
            "[Phase3] Ownership lookup failed for installation_id=%d: %s",
            installation_id, _lookup_exc,
        )

    # 9. Claim review in review_runs & legacy reviews table
    # force_new=True for 'opened'/'reopened': always run a fresh review even if
    # this SHA was previously reviewed (user closed+reopened or re-opened after fix).
    force_new = action in {"opened", "reopened"}
    claim_res = claim_review_run(
        installation_id=installation_id,
        owner=owner,
        repo=repo,
        pr_number=pr_number,
        commit_sha=commit_sha,
        force_new=force_new,
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