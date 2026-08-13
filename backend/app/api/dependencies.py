"""
FastAPI dependencies — Phase 3 multi-user SaaS.

Provides the get_current_user dependency that all authenticated endpoints use.

Clients may authenticate via:
  1. HttpOnly cookie:       Cookie: session=<jwt>   (preferred for browser clients)
  2. Authorization header:  Authorization: Bearer <jwt>  (backward-compatible for API clients)

Cookie auth is checked first; Bearer is the fallback.
"""

import jwt
from fastapi import Cookie, Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from app.utils.tokens import decode_session_token
from app.database.repository import get_user_by_id
from app.utils.logger import get_logger

logger = get_logger(__name__)

_bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> dict:
    """
    FastAPI dependency: validates the session token and returns the
    application user dict.

    Resolution order:
      1. Cookie: session=<jwt>
      2. Authorization: Bearer <jwt>

    Raises HTTP 401 if the token is missing, expired, or invalid.
    Raises HTTP 401 if the user no longer exists in the database.
    """
    # 1. Try HttpOnly cookie first (browser sessions)
    token: str | None = request.cookies.get("session")

    # 2. Fall back to Authorization Bearer header (API / backward-compat)
    if not token and credentials is not None:
        token = credentials.credentials

    if not token:
        has_cookies = bool(request.cookies)
        cookie_keys = list(request.cookies.keys())
        logger.warning(
            "[Auth Dependency] /user/me 401 Unauthorized — missing session token. "
            "Cookies present: %s (keys: %s), Bearer present: %s",
            has_cookies, cookie_keys, credentials is not None,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Provide a session cookie or Authorization: Bearer header.",
        )

    try:
        payload = decode_session_token(token)
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session token has expired. Please log in again.",
        )
    except jwt.InvalidTokenError as exc:
        logger.warning("Invalid session token: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid session token.",
        )

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Malformed session token: missing subject.",
        )

    user = get_user_by_id(user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found. The account may have been removed.",
        )

    return user
