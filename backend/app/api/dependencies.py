"""
FastAPI dependencies — Phase 3 multi-user SaaS.

Provides the get_current_user dependency that all authenticated endpoints use.
Clients must pass a session token in the Authorization header:

    Authorization: Bearer <session_token>
"""

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from app.utils.tokens import decode_session_token
from app.database.repository import get_user_by_id
from app.utils.logger import get_logger

logger = get_logger(__name__)

_bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> dict:
    """
    FastAPI dependency: validates the Bearer session token and returns the
    application user dict.

    Raises HTTP 401 if the token is missing, expired, or invalid.
    Raises HTTP 401 if the user no longer exists in the database.
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Include 'Authorization: Bearer <token>' header.",
        )

    try:
        payload = decode_session_token(credentials.credentials)
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
