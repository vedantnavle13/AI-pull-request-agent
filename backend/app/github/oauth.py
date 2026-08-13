"""
GitHub OAuth helpers — Phase 3 multi-user SaaS.

These functions implement the GitHub OAuth web application flow so that
users can sign in to our application.

Reference:
  https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/identifying-and-authorizing-users-for-github-apps
"""

import httpx
from app.utils.logger import get_logger

logger = get_logger(__name__)


def exchange_code_for_token(
    code: str,
    client_id: str,
    client_secret: str,
) -> str:
    """
    Exchange a GitHub OAuth authorization code for a user access token.

    Args:
        code:          The 'code' query parameter received in the OAuth callback.
        client_id:     GitHub App / OAuth App Client ID.
        client_secret: GitHub App / OAuth App Client Secret.

    Returns:
        The user access token string.

    Raises:
        ValueError: If GitHub returns an error instead of a token.
        httpx.HTTPError: On network / HTTP failure.
    """
    response = httpx.post(
        "https://github.com/login/oauth/access_token",
        headers={"Accept": "application/json"},
        data={
            "client_id":     client_id,
            "client_secret": client_secret,
            "code":          code,
        },
        timeout=15,
    )
    response.raise_for_status()
    data = response.json()

    if "error" in data:
        raise ValueError(
            f"GitHub OAuth token exchange failed: {data.get('error')} — "
            f"{data.get('error_description', '')}"
        )

    token = data.get("access_token")
    if not token:
        raise ValueError("GitHub OAuth response did not contain access_token")

    return token


def get_github_user(access_token: str) -> dict:
    """
    Fetch the authenticated user's GitHub profile using an OAuth access token.

    Returns a dict with at least:
        id              (int)  — GitHub user ID
        login           (str)  — GitHub username
        avatar_url      (str)
        email           (str | None)

    Raises:
        httpx.HTTPError: On network / HTTP failure.
    """
    response = httpx.get(
        "https://api.github.com/user",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Accept":        "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        timeout=15,
    )
    response.raise_for_status()
    return response.json()


def get_github_user_emails(access_token: str) -> list[dict]:
    """
    Fetch the authenticated user's verified email addresses.

    Returns the primary verified email if available, otherwise None.
    Requires the 'user:email' OAuth scope.
    """
    try:
        response = httpx.get(
            "https://api.github.com/user/emails",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept":        "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=15,
        )
        response.raise_for_status()
        return response.json()
    except Exception as exc:
        logger.warning("Could not fetch user emails: %s", exc)
        return []


def get_primary_email(access_token: str) -> str | None:
    """Return the user's primary verified GitHub email, or None."""
    emails = get_github_user_emails(access_token)
    for entry in emails:
        if entry.get("primary") and entry.get("verified"):
            return entry.get("email")
    return None
