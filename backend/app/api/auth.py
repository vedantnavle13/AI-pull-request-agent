"""
Authentication & installation API endpoints — Phase 3 multi-user SaaS.

Endpoints:
  GET  /auth/github/login                    Redirect to GitHub OAuth
  GET  /auth/github/callback                 GitHub OAuth callback → session token
  GET  /github/callback/installation         GitHub App installation callback
  GET  /user/me                              Current user profile
  GET  /user/installations                   Current user's GitHub installations
  GET  /user/repositories                    Current user's repositories

OAuth flow:
  1.  User visits /auth/github/login  → redirected to GitHub.
  2.  GitHub redirects back to /auth/github/callback?code=...&state=...
  3.  We exchange 'code' for a GitHub access token.
  4.  We fetch the user's GitHub profile and create/update them in our DB.
  5.  We issue a signed session JWT and return it.

Installation flow (when user also installs the GitHub App at the same time):
  GitHub can be configured to redirect to /github/callback/installation after
  the App installation completes. The query string will contain:
      installation_id=<int>&setup_action=install&code=<oauth_code>
  We handle both the OAuth code (log the user in) and the installation ID
  (associate it with the user and sync repositories) in one request.
"""

import secrets

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse, JSONResponse

from app.config import (
    FRONTEND_URL,
    GITHUB_CLIENT_ID,
    GITHUB_CLIENT_SECRET,
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
# Maps state token → metadata dict (e.g. pending_installation_id).
# State tokens are single-use and short-lived — this in-memory dict is
# acceptable for a single-process deployment. A multi-process/Gunicorn
# deployment should use Redis for this.
_STATE_STORE: dict[str, dict] = {}
_MAX_STATES = 500  # Prevent unbounded growth


def _generate_state(metadata: dict | None = None) -> str:
    state = secrets.token_urlsafe(32)
    if len(_STATE_STORE) >= _MAX_STATES:
        # Evict oldest entry to prevent unbounded growth
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
    If installation_id is provided, it will be remembered in the state and
    associated with the user after they log in.
    """
    _check_oauth_configured()

    metadata: dict = {}
    if installation_id is not None:
        metadata["pending_installation_id"] = installation_id

    state = _generate_state(metadata)
    return RedirectResponse(url=_build_github_oauth_url(state))


@router.get("/auth/github/callback")
async def github_callback(
    code: str = Query(..., description="OAuth authorization code from GitHub"),
    state: str = Query(..., description="CSRF state token"),
    error: str | None = Query(None),
    error_description: str | None = Query(None),
):
    """
    GitHub OAuth callback endpoint.

    GitHub redirects here after the user authorizes (or denies) the OAuth request.
    On success, exchanges the code for a token, upserts the user, and returns a
    session JWT.
    """
    _check_oauth_configured()

    # 1. Handle user denial
    if error:
        logger.warning("GitHub OAuth error: %s — %s", error, error_description)
        return RedirectResponse(
            url=f"{FRONTEND_URL}/auth/error?reason={error}",
        )

    # 2. Verify and consume state
    state_data = _consume_state(state)
    if state_data is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired OAuth state. Please start the login flow again.",
        )

    # 3. Exchange code → access token
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

    # 5. Optionally fetch verified email (best-effort)
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
        "[Auth] User logged in: %s (id=%s github_id=%s)",
        user["github_username"], user["id"], user["github_user_id"],
    )

    # 7. If there was a pending installation_id in the state, associate it
    pending_installation_id = state_data.get("pending_installation_id")
    if pending_installation_id:
        await _associate_installation(
            user_id=user["id"],
            installation_id=pending_installation_id,
        )

    # 8. Issue session token
    session_token = create_session_token(
        user_id=user["id"],
        extra_claims={
            "github_username": user["github_username"],
            "github_user_id":  user["github_user_id"],
        },
    )

    return JSONResponse(
        content={
            "token":    session_token,
            "token_type": "Bearer",
            "user": {
                "id":                user["id"],
                "github_username":   user["github_username"],
                "github_avatar_url": user["github_avatar_url"],
                "email":             user["email"],
            },
        }
    )


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
    Query parameters provided by GitHub:
        installation_id: numeric ID of the installation
        setup_action:    'install' | 'update' | 'delete'
        code:            OAuth code (only if 'Request user authorization' is enabled in App settings)

    If 'code' is present, we log the user in immediately and associate the
    installation. Otherwise, we redirect to the login flow with the
    installation_id embedded in the state.
    """
    _check_oauth_configured()

    logger.info(
        "[Installation] Callback received installation_id=%d action=%s has_code=%s",
        installation_id, setup_action, bool(code),
    )

    if setup_action == "delete":
        # Uninstallation is handled via webhook (installation event).
        # For now just return a success response.
        return JSONResponse({"status": "uninstalled", "installation_id": installation_id})

    # If we have an OAuth code, we can log the user in immediately
    if code:
        _check_oauth_configured()
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
            # Fall through to redirect flow
            state = _generate_state({"pending_installation_id": installation_id})
            return RedirectResponse(url=_build_github_oauth_url(state))

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

        # Redirect to frontend with token in fragment (avoids server logs)
        return RedirectResponse(
            url=f"{FRONTEND_URL}/auth/success#token={session_token}"
        )

    # No OAuth code — redirect through the login flow
    state_token = _generate_state({"pending_installation_id": installation_id})
    return RedirectResponse(url=_build_github_oauth_url(state_token))


async def _associate_installation(user_id: str, installation_id: int) -> None:
    """
    Fetch installation metadata from GitHub, save it to the DB,
    and sync repositories.  Best-effort — errors are logged, not raised.
    """
    try:
        # Fetch installation info from GitHub App API
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

        # Sync repositories
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
    A user cannot see another user's repositories.
    """
    repos = get_repositories_for_user(user_id=current_user["id"])
    return {"repositories": repos}
