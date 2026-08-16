"""
Authentication & installation API endpoints — Phase 3/4 multi-user SaaS.

Endpoints:
  GET  /auth/github/login                    Redirect to GitHub OAuth
  GET  /auth/github/callback                 GitHub OAuth callback → sets HttpOnly cookie → redirect to frontend
  GET  /auth/github/app-info                 Returns public app slug for frontend Install button
  POST /auth/logout                          Clears session cookie
  GET  /github/callback/installation         GitHub App installation callback
  GET  /user/me                              Current user profile
  GET  /user/installations                   Current user's GitHub installations
  GET  /user/repositories                    Current user's repositories
  GET  /user/reviews                         Current user's recent review_runs

OAuth flow (browser):
  1.  User visits /auth/github/login  → redirected to GitHub.
  2.  GitHub redirects back to /auth/github/callback?code=...&state=...
  3.  We exchange 'code' for a GitHub access token.
  4.  We fetch the user's GitHub profile and create/update them in our DB.
  5.  We issue a signed session JWT, set it as an HttpOnly cookie.
  6.  We redirect to FRONTEND_URL/dashboard.
  7.  Browser calls /user/me with the cookie on every page load.

Installation flow:
  GitHub redirects to /github/callback/installation after App installation.
  If "Request user authorization" is enabled in the App settings, GitHub
  sends both installation_id and a code.  We handle both in one request.
"""

import secrets
import hmac
import hashlib
import json
import base64
import time

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import RedirectResponse, JSONResponse

from app.config import (
    FRONTEND_URL,
    GITHUB_CLIENT_ID,
    GITHUB_CLIENT_SECRET,
    GITHUB_APP_SLUG,
    SESSION_COOKIE_NAME,
    SESSION_COOKIE_MAX_AGE,
    APP_SECRET_KEY,
)
from app.github.oauth import (
    exchange_code_for_token,
    get_github_user,
    get_primary_email,
)
from app.github.installation_sync import (
    sync_installation_repositories,
    _fetch_installation_info,
)
from app.database.repository import (
    upsert_user,
    upsert_github_installation,
    upsert_github_installation_orphan,
    get_installation_by_installation_id,
    get_installations_for_user,
    get_repositories_for_user,
    get_reviews_for_user,
    upsert_repository,
    claim_orphan_installations_for_user,
)
from app.utils.tokens import create_session_token
from app.api.dependencies import get_current_user
from app.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(tags=["auth"])

# ---------------------------------------------------------------------------
# OAuth state — HMAC-signed stateless tokens (no server-side storage needed)
#
# The old in-memory _STATE_STORE was wiped on every Render backend
# spindown/restart, causing "Invalid or expired OAuth state" errors on
# callback. Signed tokens survive any number of restarts.
# ---------------------------------------------------------------------------
_STATE_EXPIRY_SECONDS = 600  # 10 minutes


def _generate_state(metadata: dict | None = None) -> str:
    """
    Create a CSRF state token that encodes its own validity.
    Format: base64(payload).hmac_signature
    No server-side storage required.
    """
    payload = {
        "t": int(time.time()),            # issued-at timestamp
        "n": secrets.token_urlsafe(16),   # nonce for uniqueness
        "m": metadata or {},              # caller metadata
    }
    payload_json = json.dumps(payload, separators=(',', ':'), sort_keys=True)
    payload_b64 = base64.urlsafe_b64encode(payload_json.encode()).decode().rstrip('=')
    sig = hmac.new(
        APP_SECRET_KEY.encode(), payload_b64.encode(), hashlib.sha256
    ).hexdigest()[:24]
    return f"{payload_b64}.{sig}"


def _consume_state(state: str) -> dict | None:
    """
    Validate and parse a state token. Returns the embedded metadata dict
    on success, or None if the token is invalid, tampered, or expired.
    """
    try:
        payload_b64, sig = state.rsplit('.', 1)
    except ValueError:
        return None

    try:
        expected_sig = hmac.new(
            APP_SECRET_KEY.encode(), payload_b64.encode(), hashlib.sha256
        ).hexdigest()[:24]
    except Exception:
        return None

    if not hmac.compare_digest(sig, expected_sig):
        logger.warning("[Auth] OAuth state HMAC mismatch — possible CSRF attempt")
        return None

    try:
        padding = '=' * (4 - len(payload_b64) % 4)
        payload_json = base64.urlsafe_b64decode(payload_b64 + padding).decode()
        payload = json.loads(payload_json)
    except Exception:
        return None

    age = time.time() - payload.get("t", 0)
    if age > _STATE_EXPIRY_SECONDS:
        logger.warning("[Auth] OAuth state expired (age=%.0fs)", age)
        return None

    return payload.get("m", {})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _check_oauth_configured():
    """Raise 503 if OAuth env vars are not set yet."""
    if not GITHUB_CLIENT_ID or not GITHUB_CLIENT_SECRET:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "GitHub OAuth is not configured. "
                "Set GITHUB_CLIENT_ID and GITHUB_CLIENT_SECRET environment variables."
            ),
        )


def _build_github_oauth_url(state: str, scope: str = "read:user,user:email") -> str:
    return (
        f"https://github.com/login/oauth/authorize"
        f"?client_id={GITHUB_CLIENT_ID}"
        f"&scope={scope}"
        f"&state={state}"
    )


def _set_session_cookie(response: Response, token: str) -> None:
    """
    Set the HttpOnly session cookie (backward-compatibility / defense-in-depth).

    PRIMARY AUTH: The frontend now uses Authorization: Bearer tokens stored
    in localStorage. The backend callback redirects to
    /auth/callback?token=<JWT>, and the frontend stores it.

    SECONDARY AUTH: This cookie is set as a fallback. The backend's
    get_current_user dependency checks Bearer header first, then falls
    back to Cookie.

    Cookie attributes:
    - SameSite=None + Secure : required for cross-origin cookie (backend ≠ frontend host)
    - HttpOnly               : prevents XSS access
    - Path=/                 : applies to all routes
    """
    import os
    frontend_url_clean = FRONTEND_URL.rstrip("/")
    is_render = os.getenv("RENDER") is not None
    is_https = (
        frontend_url_clean.startswith("https://")
        or is_render
        or os.getenv("ENVIRONMENT") == "production"
    )

    # Cross-origin (backend ≠ frontend host) requires samesite=none + secure.
    # Local dev (same host, HTTP) uses samesite=lax.
    samesite = "none" if is_https else "lax"
    secure = is_https

    logger.info(
        "[Auth Cookie] Setting session cookie — samesite=%s secure=%s httponly=True path=/",
        samesite, secure,
    )

    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=SESSION_COOKIE_MAX_AGE,
        httponly=True,
        secure=secure,
        samesite=samesite,
        path="/",
    )


@router.get("/auth/debug/cookie")
async def debug_cookie(request: Request):
    """
    Safe diagnostic endpoint — checks whether session cookie was received by backend.
    NEVER returns actual cookie token values or secrets.
    """
    has_session = "session" in request.cookies
    cookie_names = list(request.cookies.keys())
    return {
        "has_session_cookie": has_session,
        "cookie_names": cookie_names,
    }


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/auth/github/login")
async def github_login(
    installation_id: int | None = Query(None, description="Pre-fill pending installation"),
):
    """
    Initiate GitHub OAuth login.
    Redirects the user's browser to GitHub's authorization page.
    Cache-Control: no-store prevents Cloudflare from caching this redirect.
    """
    _check_oauth_configured()
    metadata: dict = {}
    if installation_id is not None:
        metadata["pending_installation_id"] = installation_id
    state = _generate_state(metadata)
    redirect_url = _build_github_oauth_url(state)
    logger.info("[Auth] /auth/github/login called — initiating OAuth redirect to GitHub")
    response = RedirectResponse(url=redirect_url)
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, private"
    return response


@router.get("/auth/github/callback")
async def github_callback(
    code: str = Query(..., description="OAuth authorization code from GitHub"),
    state: str | None = Query(None, description="CSRF state token (missing during direct installation)"),
    installation_id: int | None = Query(None, description="GitHub App installation ID (present during installation)"),
    setup_action: str | None = Query(None, description="Setup action (e.g. 'install')"),
    error: str | None = Query(None),
    error_description: str | None = Query(None),
):
    """
    GitHub OAuth callback endpoint.

    On success:
      - Exchanges the code for a GitHub token
      - Upserts the user in our database
      - Issues a session JWT
      - Sets it as an HttpOnly cookie
      - Redirects to FRONTEND_URL/dashboard
    """
    _check_oauth_configured()
    logger.info("[Auth] /auth/github/callback reached")

    # 1. Handle user denial
    if error:
        logger.warning("GitHub OAuth error: %s — %s", error, error_description)
        return RedirectResponse(url=f"{FRONTEND_URL}/auth/error?reason={error}")

    # 2. Verify and consume CSRF state
    state_data = {}
    if state:
        state_data_result = _consume_state(state)
        if state_data_result is None:
            logger.warning("[Auth] Callback state verification failed — state token invalid or expired")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid or expired OAuth state. Please start the login flow again.",
            )
        state_data = state_data_result

    # 3. Exchange code → GitHub access token
    try:
        github_token = exchange_code_for_token(
            code=code,
            client_id=GITHUB_CLIENT_ID,
            client_secret=GITHUB_CLIENT_SECRET,
        )
    except Exception as exc:
        logger.error("GitHub token exchange failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"GitHub OAuth token exchange failed: {exc}",
        )

    # 4. Fetch GitHub user profile
    try:
        gh_user = get_github_user(github_token)
    except Exception as exc:
        logger.error("Failed to fetch GitHub user: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to retrieve GitHub user profile.",
        )

    # 5. Fetch verified email (best-effort)
    try:
        email = get_primary_email(github_token)
    except Exception:
        email = gh_user.get("email")

    # 6. Upsert user in our database
    user = upsert_user(
        github_user_id=gh_user["id"],
        github_username=gh_user["login"],
        github_avatar_url=gh_user.get("avatar_url"),
        email=email,
    )
    logger.info(
        "[Auth] User successfully authenticated: username=%s, github_id=%s, user_uuid=%s",
        user["github_username"], user["github_user_id"], user["id"],
    )

    # 7a. Auto-claim any orphaned installations for this GitHub account.
    #     This recovers installations saved before OAuth completed (e.g., the
    #     user installed the app before ever logging in, or a prior callback
    #     crashed). We do this on every login — it is idempotent and cheap.
    try:
        claimed = claim_orphan_installations_for_user(
            user_id=user["id"],
            github_username=user["github_username"],
        )
        if claimed:
            logger.info(
                "[Auth] Claimed %d orphaned installation(s) for user %s: %s",
                len(claimed), user["github_username"], claimed,
            )
            # Sync repositories for each newly claimed installation
            for inst_id in claimed:
                try:
                    inst = get_installation_by_installation_id(inst_id)
                    if inst:
                        sync_installation_repositories(
                            installation_id=inst_id,
                            installation_uuid=inst["id"],
                            upsert_repo_fn=upsert_repository,
                        )
                except Exception as sync_exc:
                    logger.warning(
                        "[Auth] Failed to sync repos for claimed installation %d: %s",
                        inst_id, sync_exc,
                    )
    except Exception as claim_exc:
        logger.warning("[Auth] Orphan installation claim failed (non-fatal): %s", claim_exc)

    # 7b. Handle pending installation from state or query params
    pending_installation_id = state_data.get("pending_installation_id") or installation_id
    if pending_installation_id:
        await _associate_installation(
            user_id=user["id"],
            installation_id=pending_installation_id,
        )

    # 8. Issue session JWT
    session_token = create_session_token(
        user_id=user["id"],
        extra_claims={
            "github_username": user["github_username"],
            "github_user_id":  user["github_user_id"],
        },
    )

    # 9. Redirect to frontend with token in URL query parameter.
    #    The frontend AuthCallback page will read the token from the URL,
    #    store it in localStorage, and navigate to /dashboard.
    #    This completely bypasses all cookie/CDN/SameSite/Partitioned issues.
    from urllib.parse import urlencode
    query_params = {'token': session_token}
    if pending_installation_id:
        query_params['installation'] = 'success'
    frontend_dest = f"{FRONTEND_URL.rstrip('/')}/auth/callback?{urlencode(query_params)}"
    logger.info("[Auth] Redirecting authenticated user to frontend callback")
    redirect = RedirectResponse(url=frontend_dest, status_code=302)
    redirect.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, private"
    # Also set cookie for backward compatibility (won't break anything)
    _set_session_cookie(redirect, session_token)
    return redirect


@router.post("/auth/logout")
async def logout(response: Response):
    """
    Logout endpoint — clears the session cookie.
    Attributes MUST exactly match those used by _set_session_cookie.
    """
    import os
    frontend_url_clean = FRONTEND_URL.rstrip("/")
    is_render = os.getenv("RENDER") is not None
    is_https = (
        frontend_url_clean.startswith("https://")
        or is_render
        or os.getenv("ENVIRONMENT") == "production"
    )

    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        path="/",
        httponly=True,
        secure=is_https,
        samesite="none" if is_https else "lax",
    )
    response.headers["Cache-Control"] = "no-store"
    logger.info("[Auth] User logged out, session cookie deleted.")
    return {"status": "logged_out"}


@router.get("/auth/github/app-info")
async def github_app_info():
    """
    Return public information about the GitHub App.
    Used by the frontend to build the Install GitHub App button URL.
    No authentication required — this is public metadata.
    """
    return {
        "slug": GITHUB_APP_SLUG,
        "install_url": f"https://github.com/apps/{GITHUB_APP_SLUG}/installations/new",
    }


@router.get("/github/callback/installation")
async def github_installation_callback(
    installation_id: int = Query(..., description="GitHub App installation ID"),
    setup_action: str = Query("install"),
    code: str | None = Query(None, description="OAuth code (if 'Request user auth' is enabled)"),
    state: str | None = Query(None),
):
    """
    GitHub App installation callback.

    GitHub redirects here after a user installs (or updates) the GitHub App.
    If 'code' is present, we log the user in immediately and associate the
    installation. Otherwise, we redirect through the login flow.
    
    IMPORTANT: We ALWAYS fetch installation info and sync repositories immediately,
    even without an OAuth code. This creates an orphan installation record that
    will be associated with the user when they complete OAuth.
    """
    _check_oauth_configured()

    logger.info(
        "[Installation] Callback received installation_id=%d action=%s has_code=%s",
        installation_id, setup_action, bool(code),
    )

    if setup_action == "delete":
        return JSONResponse({"status": "uninstalled", "installation_id": installation_id})

    # ALWAYS fetch installation info and sync repositories first (creates orphan if needed)
    try:
        inst_info = _fetch_installation_info(installation_id)
        account = inst_info.get("account", {})
        
        installation_record = upsert_github_installation_orphan(
            installation_id=installation_id,
            account_id=account.get("id", 0),
            account_login=account.get("login", ""),
            account_type=account.get("type", "User"),
        )
        installation_uuid = installation_record["id"]
        
        logger.info(
            "[Installation] Created/updated orphan installation_id=%d (uuid=%s)",
            installation_id, installation_uuid,
        )
        
        synced = sync_installation_repositories(
            installation_id=installation_id,
            installation_uuid=installation_uuid,
            upsert_repo_fn=upsert_repository,
        )
        logger.info(
            "[Installation] Synced %d repos for installation_id=%d",
            len(synced), installation_id,
        )
    except Exception as exc:
        logger.error(
            "[Installation] Failed to create orphan/sync for installation_id=%d: %s",
            installation_id, exc,
        )

    # If we have an OAuth code, log the user in immediately
    if code:
        try:
            github_token = exchange_code_for_token(
                code=code,
                client_id=GITHUB_CLIENT_ID,
                client_secret=GITHUB_CLIENT_SECRET,
            )
            gh_user = get_github_user(github_token)
            email = get_primary_email(github_token)
        except Exception as exc:
            logger.error("Installation callback token exchange failed: %s", exc)
            state_token = _generate_state({"pending_installation_id": installation_id})
            return RedirectResponse(url=_build_github_oauth_url(state_token))

        user = upsert_user(
            github_user_id=gh_user["id"],
            github_username=gh_user["login"],
            github_avatar_url=gh_user.get("avatar_url"),
            email=email or gh_user.get("email"),
        )

        await _associate_installation(
            user_id=user["id"],
            installation_id=installation_id,
        )

        session_token = create_session_token(
            user_id=user["id"],
            extra_claims={
                "github_username": user["github_username"],
                "github_user_id":  user["github_user_id"],
            },
        )

        from urllib.parse import urlencode
        redirect = RedirectResponse(
            url=f"{FRONTEND_URL.rstrip('/')}/auth/callback?{urlencode({'token': session_token, 'installation': 'success'})}",
            status_code=302,
        )
        redirect.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, private"
        _set_session_cookie(redirect, session_token)
        return redirect

    # No OAuth code — redirect through the login flow
    # The installation is already synced; user will claim it on login
    state_token = _generate_state({"pending_installation_id": installation_id})
    return RedirectResponse(url=_build_github_oauth_url(state_token))


async def _associate_installation(user_id: str, installation_id: int) -> None:
    """
    Associate a GitHub App installation with a user.
    
    Handles two cases:
    1. Orphan installation (created by webhook before OAuth) — update user_id
    2. New installation — create new record with user_id
    
    Then sync repositories.
    """
    try:
        # Check if installation already exists (orphan or associated)
        existing = get_installation_by_installation_id(installation_id)
        
        if existing:
            if existing.get("user_id"):
                # Already associated with a user (could be same or different)
                if existing["user_id"] != user_id:
                    logger.warning(
                        "[Installation] Installation %d already associated with user %s, "
                        "attempting to associate with user %s",
                        installation_id, existing["user_id"], user_id,
                    )
                installation_uuid = existing["id"]
            else:
                # Orphan installation — claim it for this user
                installation_uuid = await _claim_orphan_installation(user_id, installation_id)
        else:
            # New installation — create with user_id
            inst_info = _fetch_installation_info(installation_id)
            account = inst_info.get("account", {})
            
            installation_record = upsert_github_installation(
                user_id=user_id,
                installation_id=installation_id,
                account_id=account.get("id", 0),
                account_login=account.get("login", ""),
                account_type=account.get("type", "User"),
            )
            installation_uuid = installation_record["id"]
        
        logger.info(
            "[Installation] Associated installation_id=%d with user_id=%s (uuid=%s)",
            installation_id, user_id, installation_uuid,
        )
        
        synced = sync_installation_repositories(
            installation_id=installation_id,
            installation_uuid=installation_uuid,
            upsert_repo_fn=upsert_repository,
        )
        logger.info(
            "[Installation] Synced %d repos for installation_id=%d",
            len(synced), installation_id,
        )
        
    except Exception as exc:
        logger.error(
            "[Installation] Failed to associate installation_id=%d for user_id=%s: %s",
            installation_id, user_id, exc,
        )


async def _claim_orphan_installation(user_id: str, installation_id: int) -> str:
    """
    Update an orphan installation (user_id=NULL) to associate it with a user.
    Returns the installation UUID.
    """
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE github_installations
                SET user_id = %s, updated_at = NOW()
                WHERE installation_id = %s AND user_id IS NULL
                RETURNING id
                """,
                (user_id, installation_id),
            )
            row = cur.fetchone()
        conn.commit()
        
        if row:
            return str(row[0])
        
        # If no row updated, installation might have been claimed by another user
        # or doesn't exist. Fall back to fetching info and upserting.
        inst_info = _fetch_installation_info(installation_id)
        account = inst_info.get("account", {})
        installation_record = upsert_github_installation(
            user_id=user_id,
            installation_id=installation_id,
            account_id=account.get("id", 0),
            account_login=account.get("login", ""),
            account_type=account.get("type", "User"),
        )
        return installation_record["id"]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# User-facing endpoints (require authentication)
# ---------------------------------------------------------------------------

@router.get("/user/me")
async def get_me(
    request: Request,
    response: Response,
    current_user: dict = Depends(get_current_user),
):
    """Return the current user's profile. No-store prevents CDN caching of user-specific data."""
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, private"
    response.headers["Pragma"] = "no-cache"
    return {
        "id":                current_user["id"],
        "github_username":   current_user["github_username"],
        "github_avatar_url": current_user["github_avatar_url"],
        "email":             current_user["email"],
        "created_at":        current_user["created_at"],
    }


@router.get("/user/installations")
async def list_installations(current_user: dict = Depends(get_current_user)):
    """Return all GitHub App installations for the current user."""
    installations = get_installations_for_user(user_id=current_user["id"])
    return {"installations": installations}


@router.get("/user/repositories")
async def list_repositories(current_user: dict = Depends(get_current_user)):
    """
    Return all repositories accessible to the current user.
    Only repositories from the user's own installations are returned.
    """
    repos = get_repositories_for_user(user_id=current_user["id"])
    return {"repositories": repos}


@router.post("/user/sync-repositories")
async def sync_repositories(current_user: dict = Depends(get_current_user)):
    """
    Re-sync all repositories for all of the current user's GitHub App
    installations directly from the GitHub API.

    Any user can call this at any time to refresh their repo list after
    adding or removing repos in GitHub App settings. This is idempotent.
    """
    installations = get_installations_for_user(user_id=current_user["id"])
    total_synced = 0
    errors = []

    for inst in installations:
        installation_id  = inst["installation_id"]
        installation_uuid = inst["id"]
        try:
            synced = sync_installation_repositories(
                installation_id=installation_id,
                installation_uuid=installation_uuid,
                upsert_repo_fn=upsert_repository,
            )
            total_synced += len(synced)
            logger.info(
                "[SyncRepos] Synced %d repos for installation_id=%d user=%s",
                len(synced), installation_id, current_user["github_username"],
            )
        except Exception as exc:
            logger.error(
                "[SyncRepos] Failed to sync installation_id=%d: %s",
                installation_id, exc,
            )
            errors.append({"installation_id": installation_id, "error": str(exc)})

    return {
        "synced": total_synced,
        "installations": len(installations),
        "errors": errors,
    }


@router.get("/user/reviews")
async def list_user_reviews(
    repository: str | None = Query(None, description="Filter by owner/repo"),
    limit: int = Query(50, ge=1, le=200),
    current_user: dict = Depends(get_current_user),
):
    """
    Return recent review_runs for the authenticated user's repositories.

    Ownership is enforced at the SQL level via the github_installations join.
    Optionally filter to a single repository with ?repository=owner/repo.
    """
    reviews = get_reviews_for_user(
        user_id=current_user["id"],
        limit=limit,
        full_name=repository,
    )
    return {"reviews": reviews}
