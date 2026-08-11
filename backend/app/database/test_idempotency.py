"""
Tests for the claim_review / start_review idempotency state machine.

All DB calls are mocked — zero real Postgres, zero Gemini, zero network.

Required test cases (from spec):
  1. Same PR + same SHA → second worker skips.
  2. Same PR + different SHA → new review runs.
  3. Failed review → retry is allowed.
  4. Fresh PROCESSING review → duplicate worker skips.
  5. Stale PROCESSING review → retry is allowed.
  6. Two concurrent workers → only one successfully claims.
"""

from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

REPO = "owner/repo"
PR   = 42


def _make_conn(
    select_row: tuple | None,
    update_row: tuple | None = (999, "PROCESSING"),
) -> MagicMock:
    """
    Build a mock psycopg connection for start_review().

    start_review() uses:
      1. First `with conn.cursor() as cursor:` block:
         - 1st cursor.fetchone() -> returns select_row (diagnostics SELECT)
         - 2nd cursor.fetchone() -> returns update_row (UPDATE RETURNING)
      2. Optional second `with conn.cursor() as cursor:` block (if update_row is None):
         - 1st cursor.fetchone() -> returns select_row (re-fetch for skip reason log)
    """

    cursor1 = MagicMock()
    cursor1.fetchone.side_effect = [select_row, update_row]

    cursor2 = MagicMock()
    cursor2.fetchone.side_effect = [select_row]

    cm1 = MagicMock()
    cm1.__enter__ = lambda s: cursor1
    cm1.__exit__  = MagicMock(return_value=False)

    cm2 = MagicMock()
    cm2.__enter__ = lambda s: cursor2
    cm2.__exit__  = MagicMock(return_value=False)

    conn = MagicMock()
    conn.cursor.side_effect = [cm1, cm2]
    return conn


def _make_claim_conn(fetchone_val: tuple | None) -> MagicMock:
    """Helper for claim_review() which opens 1 cursor block and calls fetchone once."""
    cursor = MagicMock()
    cursor.fetchone.return_value = fetchone_val

    cm = MagicMock()
    cm.__enter__ = lambda s: cursor
    cm.__exit__  = MagicMock(return_value=False)

    conn = MagicMock()
    conn.cursor.return_value = cm
    return conn


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


# ---------------------------------------------------------------------------
# 1. Same PR + same SHA → second worker skips (COMPLETED row)
# ---------------------------------------------------------------------------

def test_same_sha_second_worker_skips():
    """Once a review is COMPLETED, start_review returns False."""
    existing_row = (1, "COMPLETED", _now() - timedelta(minutes=1), _now())
    conn = _make_conn(select_row=existing_row, update_row=None)

    with patch("app.database.repository.get_connection", return_value=conn):
        from app.database.repository import start_review
        result = start_review(REPO, PR, "sha_abc")

    assert result is False, "COMPLETED → must skip"


# ---------------------------------------------------------------------------
# 2. Same PR + different SHA → new review runs (QUEUED row)
# ---------------------------------------------------------------------------

def test_different_sha_new_review_runs():
    """A QUEUED row for a new SHA is claimed immediately."""
    existing_row = (2, "QUEUED", None, None)
    conn = _make_conn(select_row=existing_row, update_row=(2, "PROCESSING"))

    with patch("app.database.repository.get_connection", return_value=conn):
        from app.database.repository import start_review
        result = start_review(REPO, PR, "sha_new")

    assert result is True, "QUEUED → must be claimed"


# ---------------------------------------------------------------------------
# 3. Failed review → retry is allowed
# ---------------------------------------------------------------------------

def test_failed_review_retry_allowed():
    """A FAILED review may be retried — start_review returns True."""
    existing_row = (3, "FAILED", _now() - timedelta(minutes=5), _now())
    conn = _make_conn(select_row=existing_row, update_row=(3, "PROCESSING"))

    with patch("app.database.repository.get_connection", return_value=conn):
        from app.database.repository import start_review
        result = start_review(REPO, PR, "sha_failed")

    assert result is True, "FAILED → retry must be allowed"


# ---------------------------------------------------------------------------
# 4. Fresh PROCESSING review → duplicate worker skips
# ---------------------------------------------------------------------------

def test_fresh_processing_duplicate_worker_skips():
    """
    If started_at is recent (< STALE_PROCESSING_MINUTES ago),
    another worker must NOT claim it.
    """
    existing_row = (4, "PROCESSING", _now() - timedelta(seconds=30), None)
    conn = _make_conn(select_row=existing_row, update_row=None)

    with patch("app.database.repository.get_connection", return_value=conn):
        from app.database.repository import start_review
        result = start_review(REPO, PR, "sha_fresh")

    assert result is False, "Fresh PROCESSING → duplicate worker must skip"


# ---------------------------------------------------------------------------
# 5. Stale PROCESSING review → retry is allowed
# ---------------------------------------------------------------------------

def test_stale_processing_retry_allowed():
    """
    If started_at is older than STALE_PROCESSING_MINUTES,
    a new worker may claim it (hung worker recovery).
    """
    existing_row = (5, "PROCESSING", _now() - timedelta(hours=1), None)
    conn = _make_conn(select_row=existing_row, update_row=(5, "PROCESSING"))

    with patch("app.database.repository.get_connection", return_value=conn):
        from app.database.repository import start_review
        result = start_review(REPO, PR, "sha_stale")

    assert result is True, "Stale PROCESSING → retry must be allowed"


# ---------------------------------------------------------------------------
# 6. Two concurrent workers → only one successfully claims
# ---------------------------------------------------------------------------

def test_two_concurrent_workers_only_one_claims():
    """
    Simulate two concurrent workers calling start_review for the same SHA.
    Worker A wins (UPDATE returns a row). Worker B loses (UPDATE returns None).
    Both must be called; only A returns True.
    """
    existing_queued     = (6, "QUEUED",      None,  None)
    existing_processing = (6, "PROCESSING",  _now(), None)

    conn_a = _make_conn(select_row=existing_queued,      update_row=(6, "PROCESSING"))
    conn_b = _make_conn(select_row=existing_processing,  update_row=None)

    results = []

    with patch("app.database.repository.get_connection") as mock_gc:
        from app.database.repository import start_review

        mock_gc.return_value = conn_a
        results.append(start_review(REPO, PR, "sha_concurrent"))

        mock_gc.return_value = conn_b
        results.append(start_review(REPO, PR, "sha_concurrent"))

    assert results[0] is True,  "Worker A must claim the review"
    assert results[1] is False, "Worker B must be rejected"
    assert results.count(True) == 1, "Exactly one worker must win"


# ---------------------------------------------------------------------------
# 7. claim_review (webhook-side) — new SHA is always accepted
# ---------------------------------------------------------------------------

def test_claim_review_new_sha_accepted():
    """claim_review inserts a new QUEUED row and returns True."""
    conn = _make_claim_conn(fetchone_val=(99,))  # RETURNING id

    with patch("app.database.repository.get_connection", return_value=conn):
        from app.database.repository import claim_review
        result = claim_review(REPO, PR, "sha_brand_new")

    assert result is True


# ---------------------------------------------------------------------------
# 8. claim_review — duplicate delivery returns False
# ---------------------------------------------------------------------------

def test_claim_review_duplicate_delivery_returns_false():
    """claim_review returns False when the SHA already exists (ON CONFLICT)."""
    conn = _make_claim_conn(fetchone_val=None)  # RETURNING id — nothing inserted

    with patch("app.database.repository.get_connection", return_value=conn):
        from app.database.repository import claim_review
        result = claim_review(REPO, PR, "sha_existing")

    assert result is False
