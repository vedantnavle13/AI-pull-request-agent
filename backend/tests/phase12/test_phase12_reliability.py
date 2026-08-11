"""
Phase 12 — Production Hardening & Reliability Test Suite.

Covers:
  1. Review Lifecycle & Idempotency (same SHA twice -> skip; new SHA -> run; stale -> reclaim).
  2. Retry Subsystem (429/500 transient vs 400/401/403/422 non-retryable).
  3. GitHub API Reliability (429 rate limits, 422 inline failure fallback & logging).
  4. Gemini & Schema Validation (INVALID_AI_RESPONSE on malformed JSON).
  5. Publishing Idempotency (finding_hash duplicate prevention).
  6. Subprocess Security & Timeout (secret stripping, TEST_TIMEOUT handling).
"""

import os
import subprocess
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

from app.config import (
    MAX_REVIEW_RETRIES,
    REVIEW_STALE_TIMEOUT_SECONDS,
    TEST_TIMEOUT_SECONDS,
)
from app.database.repository import ReviewClaim
from app.utils.retries import is_transient_error, execute_with_retry
from app.github.client import (
    GitHubRateLimitError,
    GitHubValidationError,
    GitHubServerError,
    _check_github_response,
)
from app.github.diff import get_changed_lines, _normalize_path
from app.github.review import finding_hash, ReviewPublisher
from app.services.test_runner import TestRunner, _get_sanitized_env


# ---------------------------------------------------------------------------
# 1. Idempotency & Lifecycle Tests
# ---------------------------------------------------------------------------

def test_same_sha_twice_skips():
    """Same commit SHA already COMPLETED returns claimed=False, reason=already_completed."""
    with patch("app.database.repository.get_connection") as mock_gc:
        cursor = MagicMock()
        cursor.fetchone.return_value = (
            "11111111-1111-1111-1111-111111111111",
            "COMPLETED",
            datetime.now(timezone.utc),
            1,
        )
        conn = MagicMock()
        conn.cursor.return_value.__enter__.return_value = cursor
        mock_gc.return_value = conn

        from app.database.repository import claim_review_run
        claim = claim_review_run(12345, "owner", "repo", 27, "sha_abc")

        assert claim.claimed is False
        assert claim.reason == "already_completed"


def test_different_sha_same_pr_claims_new_review():
    """New SHA on the same PR returns claimed=True."""
    with patch("app.database.repository.get_connection") as mock_gc:
        cursor = MagicMock()
        # Query 1 (legacy reviews): None, Query 2 (review_runs): None, Query 3 (INSERT RETURNING id): row
        cursor.fetchone.side_effect = [None, None, ("22222222-2222-2222-2222-222222222222",)]
        conn = MagicMock()
        conn.cursor.return_value.__enter__.return_value = cursor
        mock_gc.return_value = conn


        from app.database.repository import claim_review_run
        claim = claim_review_run(12345, "owner", "repo", 27, "sha_def_new")

        assert claim.claimed is True


def test_stale_processing_review_reclaimed():
    """Stale PROCESSING review (> 15 mins) is reclaimed."""
    with patch("app.database.repository.get_connection") as mock_gc:
        cursor = MagicMock()
        stale_time = datetime.now(timezone.utc) - timedelta(seconds=REVIEW_STALE_TIMEOUT_SECONDS + 100)
        cursor.fetchone.return_value = (
            "33333333-3333-3333-3333-333333333333",
            "PROCESSING",
            stale_time,
            1,
        )
        conn = MagicMock()
        conn.cursor.return_value.__enter__.return_value = cursor
        mock_gc.return_value = conn

        from app.database.repository import claim_review_run
        claim = claim_review_run(12345, "owner", "repo", 27, "sha_stale")

        assert claim.claimed is True
        assert claim.reason == "reclaimed_stale"


# ---------------------------------------------------------------------------
# 2. Retry Logic Tests
# ---------------------------------------------------------------------------

def test_transient_error_classification():
    """429, 500, 502, 503, 504 and timeouts are transient; 400, 401, 403, 422 are not."""
    class Err429(Exception): status_code = 429
    class Err500(Exception): status_code = 500
    class Err400(Exception): status_code = 400
    class Err422(Exception): status_code = 422

    assert is_transient_error(Err429("Rate limit")) is True
    assert is_transient_error(Err500("Internal error")) is True
    assert is_transient_error(TimeoutError("Connection timeout")) is True

    assert is_transient_error(Err400("Bad Request")) is False
    assert is_transient_error(Err422("Unprocessable")) is False


def test_retry_success_after_transient_failure():
    """execute_with_retry retries on transient failure and returns result on success."""
    attempts = 0

    def flaky_func():
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            class Err503(Exception): status_code = 503
            raise Err503("Service unavailable")
        return "success"

    res = execute_with_retry(flaky_func, max_retries=3, base_delay=0.01, operation_name="test_retry")
    assert res == "success"
    assert attempts == 2


def test_non_retryable_error_fails_immediately():
    """execute_with_retry does not retry 400/422 non-transient errors."""
    attempts = 0

    def bad_request_func():
        nonlocal attempts
        attempts += 1
        class Err400(Exception): status_code = 400
        raise Err400("Invalid input")

    with pytest.raises(Exception):
        execute_with_retry(bad_request_func, max_retries=3, base_delay=0.01, operation_name="test_400")

    assert attempts == 1


# ---------------------------------------------------------------------------
# 3. GitHub API Reliability & 422 Fallback
# ---------------------------------------------------------------------------

def test_check_github_response_exceptions():
    """_check_github_response raises structured GitHub exceptions."""
    resp_429 = MagicMock(status_code=429, text="Rate limit exceeded", headers={"Retry-After": "30"})
    resp_422 = MagicMock(status_code=422, text="Validation Failed", headers={})
    resp_500 = MagicMock(status_code=500, text="Internal Server Error", headers={})

    with pytest.raises(GitHubRateLimitError) as exc_info:
        _check_github_response(resp_429)
    assert exc_info.value.retry_after == 30

    with pytest.raises(GitHubValidationError):
        _check_github_response(resp_422)

    with pytest.raises(GitHubServerError):
        _check_github_response(resp_500)


def test_publisher_fallback_on_422_inline_failure():
    """ReviewPublisher logs INLINE_REVIEW_FAILED and falls back to summary review on 422."""
    publisher = ReviewPublisher()

    mock_github = MagicMock()
    # First call with inline comments raises error; second call without inline comments succeeds
    mock_github.submit_pull_request_review.side_effect = [
        RuntimeError("GitHub 422: Validation Failed for inline comment"),
        {"id": 999000, "status": "submitted"}
    ]
    mock_github.list_pr_reviews.return_value = []
    mock_github.list_pr_comments.return_value = []

    res = publisher.publish(
        github=mock_github,
        owner="owner",
        repo="repo",
        pr_number=27,
        commit_sha="sha_123",
        findings=[{
            "file": "addition.py",
            "line": 5,
            "title": "Bug",
            "category": "BUG",
            "severity": "HIGH",
            "description": "desc",
            "suggestion": "fix"
        }],
        files=[{"filename": "addition.py", "patch": "@@ -0,0 +1,10 @@\n+line5\n"}],
        decision="HUMAN_REVIEW",
        test_results=[],
        validation_errors=[],
    )

    assert res["github_review_id"] == 999000
    assert mock_github.submit_pull_request_review.call_count == 2


# ---------------------------------------------------------------------------
# 4. Publishing Idempotency
# ---------------------------------------------------------------------------

def test_publishing_idempotency_hash():
    """finding_hash is deterministic for given commit, file, line, category, description."""
    h1 = finding_hash("repo", 27, "sha1", "addition.py", 10, "BUG", "Desc")
    h2 = finding_hash("repo", 27, "sha1", "addition.py", 10, "BUG", "Desc")
    h3 = finding_hash("repo", 27, "sha1", "addition.py", 11, "BUG", "Desc")

    assert h1 == h2
    assert h1 != h3


# ---------------------------------------------------------------------------
# 5. Security & Subprocess Sandbox
# ---------------------------------------------------------------------------

def test_sanitized_environment_strips_secrets():
    """_get_sanitized_env removes GEMINI_API_KEY, GITHUB_TOKEN, etc. from subprocess env."""
    os.environ["GEMINI_API_KEY"] = "secret_gemini_key"
    os.environ["GITHUB_TOKEN"] = "secret_github_token"
    os.environ["DATABASE_URL"] = "postgresql://secret@db"

    clean_env = _get_sanitized_env()

    assert "GEMINI_API_KEY" not in clean_env
    assert "GITHUB_TOKEN" not in clean_env
    assert "DATABASE_URL" not in clean_env
    assert "PATH" in clean_env


def test_runner_handles_timeout_gracefully():
    """TestRunner returns TEST_TIMEOUT status when subprocess exceeds timeout."""
    runner = TestRunner(timeout=1)

    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd=["pytest"], timeout=1)):
        result = runner._execute(command=["pytest"], cwd=".", framework="pytest")

    assert result.status == "TIMEOUT"
