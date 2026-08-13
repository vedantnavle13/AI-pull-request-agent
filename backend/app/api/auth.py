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

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import RedirectResponse, JSONResponse

from app.config import (
    FRONTEND_URL,
    GITHUB_CLIENT_ID,
    GITHUB_CLIENT_SECRET,
    GITHUB_APP_SLUG,
    SESSION_COOKIE_NAME,
    SESSION_COOKIE_MAX_AGE,
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
    get_installation_by_installation_id,
    get_installations_for_user,
    get_repositories_for_user,
    get_reviews_for_user,
    upsert_repository,
)
from app.utils.tokens import create_session_token
from app.api.dependencies import get_current_user
from app.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(tags=["auth"])

# ---------------------------------------------------------------------------
# OAuth state store (in-memory; replace with Redis for production scale)
# ---------------------------------------------------------------------------
_STATE_STORE: dict[str, dict] = {}
_MAX_STATES = 500


def _generate_state(metadata: dict | None = None) -> str:
    state = secrets.token_urlsafe(32)
    if len(_STATE_STORE) >= _MAX_STATES:
        oldest = next(iter(_STATE_STORE))
        del _STATE_STORE[oldest]
    _STATE_STORE[state] = metadata or {}
    return state


def _consume_state(state: str) -> dict | None:
    return _STATE_STORE.pop(state, None)


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
    Set the HttpOnly session cookie on any response object.

    For cross-site production HTTPS (frontend on ai-pull-request-agent.onrender.com
    and backend on ai-pull-request-agent-api.onrender.com), SameSite MUST be 'none'
    and Secure MUST be True.

    For local HTTP development (http://localhost:3000), SameSite='lax' and Secure=False
    is used because browsers reject SameSite=None without Secure over plain HTTP.
    """
    import os
    frontend_url_clean = FRONTEND_URL.rstrip("/")
    is_render = os.getenv("RENDER") is not None
    is_https = (
        frontend_url_clean.startswith("https://")
        or is_render
        or os.getenv("ENVIRONMENT") == "production"
    )

    samesite = "none" if is_https else "lax"
    secure = True if is_https else False

    logger.info(
        "[Auth Cookie Diagnostic] Emitting session cookie: samesite=%s secure=%s httponly=True path=/ is_https=%s is_render=%s frontend_url=%s",
        samesite, secure, is_https, is_render, frontend_url_clean,
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

    if is_https and "set-cookie" in response.headers:
        cookie_header = response.headers["set-cookie"]
        if "partitioned" not in cookie_header.lower():
            response.headers["set-cookie"] = cookie_header + "; Partitioned"


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
    """
    _check_oauth_configured()
    metadata: dict = {}
    if installation_id is not None:
        metadata["pending_installation_id"] = installation_id
    state = _generate_state(metadata)
    redirect_url = _build_github_oauth_url(state)
    logger.info("[Auth] /auth/github/login called — initiating OAuth redirect to GitHub")
    return RedirectResponse(url=redirect_url)


@router.get("/auth/github/callback")
async def github_callback(
    code: str = Query(..., description="OAuth authorization code from GitHub"),
    state: str = Query(..., description="CSRF state token"),
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
    state_data = _consume_state(state)
    if state_data is None:
        logger.warning("[Auth] Callback state verification failed — state token invalid or expired")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired OAuth state. Please start the login flow again.",
        )

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

    # 7. Handle pending installation from state
    pending_installation_id = state_data.get("pending_installation_id")
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

    # 9. Set HttpOnly cookie + redirect to frontend dashboard
    frontend_dest = f"{FRONTEND_URL.rstrip('/')}/dashboard"
    logger.info("[Auth] Redirecting authenticated user to %s", frontend_dest)
    redirect = RedirectResponse(url=frontend_dest, status_code=302)
    _set_session_cookie(redirect, session_token)
    return redirect


@router.post("/auth/logout")
async def logout(response: Response):
    """
    Logout endpoint — clears the session cookie.
    Must match samesite and secure attributes used when setting the cookie.
    """
    import os
    frontend_url_clean = FRONTEND_URL.rstrip("/")
    is_https = (
        frontend_url_clean.startswith("https://")
        or os.getenv("RENDER") is not None
        or os.getenv("ENVIRONMENT") == "production"
    )
    samesite = "none" if is_https else "lax"
    secure = True if is_https else False

    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        path="/",
        httponly=True,
        secure=secure,
        samesite=samesite,
    )
    if is_https and "set-cookie" in response.headers:
        cookie_header = response.headers["set-cookie"]
        if "partitioned" not in cookie_header.lower():
            response.headers["set-cookie"] = cookie_header + "; Partitioned"

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
    """
    _check_oauth_configured()

    logger.info(
        "[Installation] Callback received installation_id=%d action=%s has_code=%s",
        installation_id, setup_action, bool(code),
    )

    if setup_action == "delete":
        return JSONResponse({"status": "uninstalled", "installation_id": installation_id})

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

        redirect = RedirectResponse(url=f"{FRONTEND_URL}/dashboard?installation=success", status_code=302)
        _set_session_cookie(redirect, session_token)
        return redirect

    # No OAuth code — redirect through the login flow
    state_token = _generate_state({"pending_installation_id": installation_id})
    return RedirectResponse(url=_build_github_oauth_url(state_token))


async def _associate_installation(user_id: str, installation_id: int) -> None:
    """
    Fetch installation metadata from GitHub, save it to the DB,
    and sync repositories. Best-effort — errors are logged, not raised.
    """
    try:
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
            "[Installation] Saved installation_id=%d for user_id=%s",
            installation_id, user_id,
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


# ---------------------------------------------------------------------------
# User-facing endpoints (require authentication)
# ---------------------------------------------------------------------------

@router.get("/user/me")
async def get_me(current_user: dict = Depends(get_current_user)):
    """Return the current user's profile."""
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
