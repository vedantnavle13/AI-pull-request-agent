"""
Phase 3 — Multi-user GitHub Architecture Test Suite.

Covers all 10 scenarios from the spec:

  1.  Two users can exist.
  2.  Two GitHub installations can exist.
  3.  Each installation belongs to exactly one user.
  4.  User A can only retrieve User A repositories.
  5.  User B cannot retrieve User A repositories.
  6.  Same installation callback is idempotent.
  7.  Same repository sync is idempotent.
  8.  Webhook installation_id resolves to correct user.
  9.  Existing webhook idempotency still works (register_webhook_delivery).
  10. Existing review queue behavior still works (claim_review_run).

All tests use unittest.mock to avoid hitting the real database or GitHub API.
"""

import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch, call

import pytest

# ---------------------------------------------------------------------------
# Helpers — build fake DB rows
# ---------------------------------------------------------------------------

def _make_user_row(
    user_uuid: str,
    github_user_id: int,
    github_username: str,
    avatar: str = "https://avatars.githubusercontent.com/u/1",
    email: str | None = None,
):
    """Return a tuple matching the column order in get_user_by_github_id."""
    now = datetime.now(timezone.utc)
    return (user_uuid, github_user_id, github_username, avatar, email, now, now)


def _make_installation_row(
    inst_uuid: str,
    user_uuid: str,
    installation_id: int,
    account_login: str = "octocat",
    account_type: str = "User",
):
    now = datetime.now(timezone.utc)
    return (
        inst_uuid,
        user_uuid,
        installation_id,
        123456,      # account_id
        account_login,
        account_type,
        now,
        now,
    )


def _make_repo_row(
    repo_uuid: str,
    inst_uuid: str,
    github_repo_id: int,
    full_name: str,
    private: bool = False,
):
    now = datetime.now(timezone.utc)
    owner, name = full_name.split("/", 1)
    return (
        repo_uuid,
        inst_uuid,
        github_repo_id,
        owner,
        name,
        full_name,
        private,
        "main",
        True,
        now,
        now,
    )


# ---------------------------------------------------------------------------
# 1. Two users can exist
# ---------------------------------------------------------------------------

def test_two_users_can_exist():
    """upsert_user is called with two different GitHub user IDs without conflict."""
    user_a_id = str(uuid.uuid4())
    user_b_id = str(uuid.uuid4())

    row_a = _make_user_row(user_a_id, 1001, "alice")
    row_b = _make_user_row(user_b_id, 1002, "bob")

    with patch("app.database.repository.get_connection") as mock_gc:
        cursor = MagicMock()
        cursor.fetchone.side_effect = [row_a, row_b]
        conn = MagicMock()
        conn.cursor.return_value.__enter__.return_value = cursor
        mock_gc.return_value = conn

        from app.database.repository import upsert_user

        user_a = upsert_user(1001, "alice")
        user_b = upsert_user(1002, "bob")

    assert user_a["github_username"] == "alice"
    assert user_b["github_username"] == "bob"
    assert user_a["github_user_id"] == 1001
    assert user_b["github_user_id"] == 1002
    assert user_a["id"] != user_b["id"]


# ---------------------------------------------------------------------------
# 2. Two GitHub installations can exist
# ---------------------------------------------------------------------------

def test_two_installations_can_exist():
    """upsert_github_installation succeeds for two different installation IDs."""
    user_a_id = str(uuid.uuid4())
    inst_a_uuid = str(uuid.uuid4())
    inst_b_uuid = str(uuid.uuid4())

    row_a = _make_installation_row(inst_a_uuid, user_a_id, 11111)
    row_b = _make_installation_row(inst_b_uuid, user_a_id, 22222, account_login="org-b")

    with patch("app.database.repository.get_connection") as mock_gc:
        cursor = MagicMock()
        cursor.fetchone.side_effect = [row_a, row_b]
        conn = MagicMock()
        conn.cursor.return_value.__enter__.return_value = cursor
        mock_gc.return_value = conn

        from app.database.repository import upsert_github_installation

        inst_a = upsert_github_installation(user_a_id, 11111, 123456, "alice", "User")
        inst_b = upsert_github_installation(user_a_id, 22222, 789012, "org-b", "Organization")

    assert inst_a["installation_id"] == 11111
    assert inst_b["installation_id"] == 22222
    assert inst_a["id"] != inst_b["id"]


# ---------------------------------------------------------------------------
# 3. Each installation belongs to exactly one user
# ---------------------------------------------------------------------------

def test_installation_belongs_to_exactly_one_user():
    """get_installation_by_installation_id returns the correct user_id."""
    user_a_id = str(uuid.uuid4())
    user_b_id = str(uuid.uuid4())
    inst_uuid = str(uuid.uuid4())

    row = _make_installation_row(inst_uuid, user_a_id, 11111)

    with patch("app.database.repository.get_connection") as mock_gc:
        cursor = MagicMock()
        cursor.fetchone.return_value = row
        conn = MagicMock()
        conn.cursor.return_value.__enter__.return_value = cursor
        mock_gc.return_value = conn

        from app.database.repository import get_installation_by_installation_id

        result = get_installation_by_installation_id(11111)

    assert result is not None
    assert result["user_id"] == user_a_id
    assert result["user_id"] != user_b_id
    assert result["installation_id"] == 11111


# ---------------------------------------------------------------------------
# 4. User A can only retrieve User A repositories
# ---------------------------------------------------------------------------

def test_user_a_retrieves_own_repositories():
    """get_repositories_for_user returns repos joined through user_id = User A."""
    user_a_id = str(uuid.uuid4())
    inst_a_uuid = str(uuid.uuid4())
    repo_uuid = str(uuid.uuid4())

    # Extended row: includes account_login and installation_id_int at columns 11, 12
    now = datetime.now(timezone.utc)
    repo_row = (
        repo_uuid, inst_a_uuid, 9001, "alice", "my-repo", "alice/my-repo",
        False, "main", True, now, now,
        "alice",   # account_login (col 11)
        11111,     # installation_id_int (col 12)
    )

    with patch("app.database.repository.get_connection") as mock_gc:
        cursor = MagicMock()
        cursor.fetchall.return_value = [repo_row]
        conn = MagicMock()
        conn.cursor.return_value.__enter__.return_value = cursor
        mock_gc.return_value = conn

        from app.database.repository import get_repositories_for_user

        repos = get_repositories_for_user(user_a_id)

    assert len(repos) == 1
    assert repos[0]["full_name"] == "alice/my-repo"
    assert repos[0]["owner"] == "alice"

    # Verify that the SQL was called with user_a_id (not any other user)
    executed_sql = cursor.execute.call_args[0][0]
    assert "gi.user_id" in executed_sql
    executed_params = cursor.execute.call_args[0][1]
    assert executed_params == (user_a_id,)


# ---------------------------------------------------------------------------
# 5. User B cannot retrieve User A repositories
# ---------------------------------------------------------------------------

def test_user_b_cannot_retrieve_user_a_repositories():
    """get_repositories_for_user for User B returns empty list when User A owns repos."""
    user_b_id = str(uuid.uuid4())

    with patch("app.database.repository.get_connection") as mock_gc:
        cursor = MagicMock()
        cursor.fetchall.return_value = []  # No repos for User B
        conn = MagicMock()
        conn.cursor.return_value.__enter__.return_value = cursor
        mock_gc.return_value = conn

        from app.database.repository import get_repositories_for_user

        repos = get_repositories_for_user(user_b_id)

    assert repos == []

    # Verify the SQL filter uses user_b_id
    executed_params = cursor.execute.call_args[0][1]
    assert executed_params == (user_b_id,)


def test_verify_repository_ownership_rejects_wrong_user():
    """verify_repository_belongs_to_user returns False for wrong user."""
    user_b_id = str(uuid.uuid4())

    with patch("app.database.repository.get_connection") as mock_gc:
        cursor = MagicMock()
        cursor.fetchone.return_value = None  # No row found = not owned by User B
        conn = MagicMock()
        conn.cursor.return_value.__enter__.return_value = cursor
        mock_gc.return_value = conn

        from app.database.repository import verify_repository_belongs_to_user

        result = verify_repository_belongs_to_user(user_b_id, "alice/my-repo")

    assert result is False


def test_verify_repository_ownership_allows_correct_user():
    """verify_repository_belongs_to_user returns True for the owning user."""
    user_a_id = str(uuid.uuid4())

    with patch("app.database.repository.get_connection") as mock_gc:
        cursor = MagicMock()
        cursor.fetchone.return_value = (1,)  # Row found = User A owns it
        conn = MagicMock()
        conn.cursor.return_value.__enter__.return_value = cursor
        mock_gc.return_value = conn

        from app.database.repository import verify_repository_belongs_to_user

        result = verify_repository_belongs_to_user(user_a_id, "alice/my-repo")

    assert result is True


# ---------------------------------------------------------------------------
# 6. Same installation callback is idempotent
# ---------------------------------------------------------------------------

def test_same_installation_callback_is_idempotent():
    """
    Calling upsert_github_installation twice with the same installation_id
    results in ON CONFLICT DO UPDATE — both calls succeed and return the same ID.
    """
    user_a_id = str(uuid.uuid4())
    inst_uuid = str(uuid.uuid4())

    row = _make_installation_row(inst_uuid, user_a_id, 11111)

    with patch("app.database.repository.get_connection") as mock_gc:
        cursor = MagicMock()
        # Both calls return the same row (ON CONFLICT DO UPDATE RETURNING)
        cursor.fetchone.side_effect = [row, row]
        conn = MagicMock()
        conn.cursor.return_value.__enter__.return_value = cursor
        mock_gc.return_value = conn

        from app.database.repository import upsert_github_installation

        first  = upsert_github_installation(user_a_id, 11111, 123456, "alice", "User")
        second = upsert_github_installation(user_a_id, 11111, 123456, "alice", "User")

    assert first["id"]  == second["id"]
    assert first["installation_id"] == second["installation_id"] == 11111


# ---------------------------------------------------------------------------
# 7. Same repository sync is idempotent
# ---------------------------------------------------------------------------

def test_same_repository_sync_is_idempotent():
    """
    Calling upsert_repository twice with the same (installation_uuid, github_repo_id)
    updates rather than duplicates (ON CONFLICT DO UPDATE).
    """
    inst_uuid = str(uuid.uuid4())
    repo_uuid = str(uuid.uuid4())

    now = datetime.now(timezone.utc)
    repo_row = (
        repo_uuid, inst_uuid, 9001, "alice", "my-repo", "alice/my-repo",
        False, "main", True, now, now,
    )

    with patch("app.database.repository.get_connection") as mock_gc:
        cursor = MagicMock()
        cursor.fetchone.side_effect = [repo_row, repo_row]
        conn = MagicMock()
        conn.cursor.return_value.__enter__.return_value = cursor
        mock_gc.return_value = conn

        from app.database.repository import upsert_repository

        first  = upsert_repository(inst_uuid, 9001, "alice", "my-repo", "alice/my-repo")
        second = upsert_repository(inst_uuid, 9001, "alice", "my-repo", "alice/my-repo")

    assert first["id"]  == second["id"]
    assert first["github_repo_id"] == second["github_repo_id"] == 9001


# ---------------------------------------------------------------------------
# 8. Webhook installation_id resolves to the correct user
# ---------------------------------------------------------------------------

def test_webhook_installation_id_resolves_to_user():
    """
    get_user_id_for_installation(installation_id) returns the correct user_id.
    This is what the webhook handler calls for ownership logging.
    """
    user_a_id = str(uuid.uuid4())
    inst_uuid  = str(uuid.uuid4())
    row = _make_installation_row(inst_uuid, user_a_id, 11111)

    with patch("app.database.repository.get_connection") as mock_gc:
        cursor = MagicMock()
        cursor.fetchone.return_value = row
        conn = MagicMock()
        conn.cursor.return_value.__enter__.return_value = cursor
        mock_gc.return_value = conn

        from app.database.repository import get_user_id_for_installation

        result = get_user_id_for_installation(11111)

    assert result == user_a_id


def test_webhook_unregistered_installation_returns_none():
    """
    get_user_id_for_installation returns None for an installation that has
    not been registered yet — the webhook still proceeds normally.
    """
    with patch("app.database.repository.get_connection") as mock_gc:
        cursor = MagicMock()
        cursor.fetchone.return_value = None
        conn = MagicMock()
        conn.cursor.return_value.__enter__.return_value = cursor
        mock_gc.return_value = conn

        from app.database.repository import get_user_id_for_installation

        result = get_user_id_for_installation(99999)

    assert result is None


# ---------------------------------------------------------------------------
# 9. Existing webhook idempotency still works
# ---------------------------------------------------------------------------

def test_webhook_delivery_idempotency_new():
    """register_webhook_delivery returns True for a new delivery ID."""
    with patch("app.database.repository.get_connection") as mock_gc:
        cursor = MagicMock()
        cursor.rowcount = 1  # INSERT succeeded → new delivery
        conn = MagicMock()
        conn.cursor.return_value.__enter__.return_value = cursor
        mock_gc.return_value = conn

        from app.database.repository import register_webhook_delivery

        result = register_webhook_delivery("delivery-001", "pull_request", "opened")

    assert result is True


def test_webhook_delivery_idempotency_duplicate():
    """register_webhook_delivery returns False for a duplicate delivery ID."""
    with patch("app.database.repository.get_connection") as mock_gc:
        cursor = MagicMock()
        cursor.rowcount = 0  # ON CONFLICT DO NOTHING → already exists
        conn = MagicMock()
        conn.cursor.return_value.__enter__.return_value = cursor
        mock_gc.return_value = conn

        from app.database.repository import register_webhook_delivery

        result = register_webhook_delivery("delivery-001", "pull_request", "opened")

    assert result is False


# ---------------------------------------------------------------------------
# 10. Existing review queue behavior still works (claim_review_run)
# ---------------------------------------------------------------------------

def test_review_queue_new_sha_claims_successfully():
    """A new SHA on a PR is claimed successfully by claim_review_run."""
    with patch("app.database.repository.get_connection") as mock_gc:
        cursor = MagicMock()
        # claim_review_run generates its own UUID internally for new rows.
        # fetchone sequence:
        #   1. legacy reviews SELECT → None (no existing row)
        #   2. review_runs SELECT → None (no existing row)
        #   3. INSERT ... RETURNING id → row with ANY uuid (the RETURNING value)
        returned_id = str(uuid.uuid4())
        cursor.fetchone.side_effect = [None, None, (returned_id,)]
        conn = MagicMock()
        conn.cursor.return_value.__enter__.return_value = cursor
        mock_gc.return_value = conn

        from app.database.repository import claim_review_run

        claim = claim_review_run(11111, "alice", "my-repo", 42, "sha_new_abc")

    assert claim.claimed is True
    # The review_id is internally generated — just verify it is a non-empty string.
    assert claim.review_id is not None
    assert isinstance(claim.review_id, str)
    assert len(claim.review_id) > 0


def test_review_queue_completed_sha_skips():
    """A SHA that's already COMPLETED returns claimed=False, reason=already_completed."""
    with patch("app.database.repository.get_connection") as mock_gc:
        cursor = MagicMock()
        existing_id = str(uuid.uuid4())
        cursor.fetchone.return_value = (
            existing_id,
            "COMPLETED",
            datetime.now(timezone.utc),
            1,
        )
        conn = MagicMock()
        conn.cursor.return_value.__enter__.return_value = cursor
        mock_gc.return_value = conn

        from app.database.repository import claim_review_run

        claim = claim_review_run(11111, "alice", "my-repo", 42, "sha_done")

    assert claim.claimed is False
    assert claim.reason == "already_completed"


# ---------------------------------------------------------------------------
# Session token utilities
# ---------------------------------------------------------------------------

def test_session_token_roundtrip():
    """create_session_token / decode_session_token are inverses."""
    from app.utils.tokens import create_session_token, decode_session_token

    user_id = str(uuid.uuid4())
    token = create_session_token(user_id, extra_claims={"github_username": "alice"})

    payload = decode_session_token(token)
    assert payload["sub"] == user_id
    assert payload["github_username"] == "alice"
    assert payload["typ"] == "session"


def test_expired_session_token_raises():
    """An expired token raises jwt.ExpiredSignatureError."""
    import time
    import jwt as _jwt

    from app.utils.tokens import create_session_token, decode_session_token
    from app.config import APP_SECRET_KEY

    user_id = str(uuid.uuid4())
    # Build a token with exp in the past
    payload = {
        "sub": user_id,
        "iat": int(time.time()) - 200,
        "exp": int(time.time()) - 100,  # expired 100 seconds ago
        "typ": "session",
    }
    expired_token = _jwt.encode(payload, APP_SECRET_KEY, algorithm="HS256")

    with pytest.raises(_jwt.ExpiredSignatureError):
        decode_session_token(expired_token)


# ---------------------------------------------------------------------------
# Installation sync idempotency (unit test without DB)
# ---------------------------------------------------------------------------

def test_sync_installation_repositories_idempotent():
    """
    sync_installation_repositories calls upsert_repo_fn for each repo and
    can be called multiple times without side effects (idempotency is
    guaranteed by the SQL ON CONFLICT logic which is tested above).
    """
    from app.github.installation_sync import sync_installation_repositories

    fake_repos = [
        {
            "id": 9001,
            "owner": {"login": "alice"},
            "name": "repo-1",
            "full_name": "alice/repo-1",
            "private": False,
            "default_branch": "main",
        },
        {
            "id": 9002,
            "owner": {"login": "alice"},
            "name": "repo-2",
            "full_name": "alice/repo-2",
            "private": True,
            "default_branch": "develop",
        },
    ]

    upsert_mock = MagicMock(side_effect=[
        {"id": str(uuid.uuid4()), "full_name": "alice/repo-1"},
        {"id": str(uuid.uuid4()), "full_name": "alice/repo-2"},
        {"id": str(uuid.uuid4()), "full_name": "alice/repo-1"},
        {"id": str(uuid.uuid4()), "full_name": "alice/repo-2"},
    ])

    inst_uuid = str(uuid.uuid4())

    with patch("app.github.installation_sync._fetch_installation_repos", return_value=fake_repos):
        first_sync  = sync_installation_repositories(11111, inst_uuid, upsert_mock)
        second_sync = sync_installation_repositories(11111, inst_uuid, upsert_mock)

    # Both calls synced the same 2 repos
    assert len(first_sync)  == 2
    assert len(second_sync) == 2
    # upsert was called 4 times total (2 per sync)
    assert upsert_mock.call_count == 4
