"""
GitHub App installation repository sync — Phase 3 multi-user SaaS.

After a user installs the GitHub App, we authenticate as that installation
and fetch the list of repositories it has access to, then persist them.
"""

from typing import Generator

import requests

from app.github.auth import get_installation_token
from app.utils.logger import get_logger

logger = get_logger(__name__)

_GITHUB_API = "https://api.github.com"
_PAGE_SIZE = 100


def _fetch_installation_repos(installation_id: int) -> list[dict]:
    """
    Fetch all repositories accessible to a GitHub App installation.

    Paginates through all pages of the /installation/repositories endpoint.
    Authenticates as the installation (not as the user).

    Returns a list of repository dicts as returned by the GitHub API.
    """
    token = get_installation_token(installation_id)
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept":        "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    repos: list[dict] = []
    page = 1

    while True:
        resp = requests.get(
            f"{_GITHUB_API}/installation/repositories",
            headers=headers,
            params={"per_page": _PAGE_SIZE, "page": page},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()

        batch = data.get("repositories", [])
        repos.extend(batch)

        # Stop when we've received fewer repos than the page size — last page.
        if len(batch) < _PAGE_SIZE:
            break

        page += 1

    logger.info(
        "[InstallationSync] installation_id=%d found %d repositories",
        installation_id, len(repos),
    )
    return repos


def _fetch_installation_info(installation_id: int) -> dict:
    """
    Fetch metadata about the installation itself (account login, type, etc.)
    using a GitHub App JWT (not installation token).

    Returns the raw GitHub API response for GET /app/installations/{id}.
    """
    import time
    import jwt
    from app.config import GITHUB_APP_ID, PRIVATE_KEY_PATH

    with open(PRIVATE_KEY_PATH, "r") as f:
        private_key = f.read()

    payload = {
        "iat": int(time.time()),
        "exp": int(time.time()) + 600,
        "iss": GITHUB_APP_ID,
    }
    jwt_token = jwt.encode(payload, private_key, algorithm="RS256")

    resp = requests.get(
        f"{_GITHUB_API}/app/installations/{installation_id}",
        headers={
            "Authorization": f"Bearer {jwt_token}",
            "Accept":        "application/vnd.github+json",
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def sync_installation_repositories(
    installation_id: int,
    installation_uuid: str,
    upsert_repo_fn,
) -> list[dict]:
    """
    Sync repositories for a GitHub App installation into the database.

    Args:
        installation_id:   The numeric installation_id from GitHub.
        installation_uuid: The UUID primary key of the github_installations row.
        upsert_repo_fn:    Callable matching the signature of
                           repository.upsert_repository — injected to keep this
                           module testable without a live database connection.

    Returns:
        List of upserted (active) repository dicts from the database.

    This function is idempotent — calling it multiple times with the same
    installation_id produces the same database state (ON CONFLICT DO UPDATE).

    Repos that are no longer accessible to the installation (removed by user
    in GitHub settings) are automatically deactivated in the database.
    """
    from app.database.postgres import get_connection

    raw_repos = _fetch_installation_repos(installation_id)
    active_full_names = {repo["full_name"] for repo in raw_repos}

    synced = []
    for repo in raw_repos:
        try:
            record = upsert_repo_fn(
                installation_uuid=installation_uuid,
                github_repo_id=repo["id"],
                owner=repo["owner"]["login"],
                name=repo["name"],
                full_name=repo["full_name"],
                private=repo.get("private", False),
                default_branch=repo.get("default_branch", "main"),
            )
            synced.append(record)
        except Exception as exc:
            logger.error(
                "[InstallationSync] Failed to upsert repo %s: %s",
                repo.get("full_name"), exc,
            )

    # Deactivate any repos that are no longer in this installation's access list
    try:
        conn = get_connection()
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE repositories
                SET    active     = FALSE,
                       updated_at = NOW()
                WHERE  installation_id = %s
                  AND  active = TRUE
                  AND  full_name != ALL(%s)
                """,
                (installation_uuid, list(active_full_names) if active_full_names else [""]),
            )
            deactivated = cur.rowcount
        conn.commit()
        conn.close()
        if deactivated:
            logger.info(
                "[InstallationSync] Deactivated %d repo(s) no longer in installation_id=%d",
                deactivated, installation_id,
            )
    except Exception as exc:
        logger.error("[InstallationSync] Failed to deactivate stale repos: %s", exc)

    logger.info(
        "[InstallationSync] Synced %d/%d repositories for installation_id=%d",
        len(synced), len(raw_repos), installation_id,
    )
    return synced
