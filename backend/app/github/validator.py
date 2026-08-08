import hashlib
import hmac

from fastapi import HTTPException


def verify_signature(
    payload: bytes,
    signature: str | None,
    secret: str,
):
    if not signature:
        raise HTTPException(
            status_code=403,
            detail="Missing GitHub signature",
        )

    expected = "sha256=" + hmac.new(
        secret.encode("utf-8"),
        payload,
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(expected, signature):
        raise HTTPException(
            status_code=403,
            detail="Invalid GitHub signature",
        )