"""
Session token utilities — Phase 3 multi-user SaaS.

Issues and verifies short-lived JWTs used as application session tokens.
These are NOT GitHub tokens — they identify the user within our application.

Uses PyJWT (already in requirements as PyJWT[crypto]).
"""

import time
from typing import Any

import jwt

from app.config import APP_SECRET_KEY
from app.utils.logger import get_logger

logger = get_logger(__name__)

_ALGORITHM = "HS256"
_TOKEN_TTL_SECONDS = 60 * 60 * 24 * 7  # 7 days


def create_session_token(user_id: str, extra_claims: dict | None = None) -> str:
    """
    Create a signed JWT session token for the given user.

    Args:
        user_id:      The application user UUID (from the users table).
        extra_claims: Optional additional claims to embed (e.g. github_username).

    Returns:
        A compact JWT string.
    """
    now = int(time.time())
    payload: dict[str, Any] = {
        "sub":  user_id,
        "iat":  now,
        "exp":  now + _TOKEN_TTL_SECONDS,
        "typ":  "session",
    }
    if extra_claims:
        payload.update(extra_claims)

    return jwt.encode(payload, APP_SECRET_KEY, algorithm=_ALGORITHM)


def decode_session_token(token: str) -> dict:
    """
    Decode and verify a session token.

    Returns:
        The decoded payload dict.

    Raises:
        jwt.ExpiredSignatureError:  Token has expired.
        jwt.InvalidTokenError:      Token is malformed or signature invalid.
    """
    return jwt.decode(token, APP_SECRET_KEY, algorithms=[_ALGORITHM])
