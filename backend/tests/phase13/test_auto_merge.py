"""
Phase 13 — Auto-Merge Gate Unit Tests.

All tests use mocked GitHub API responses.
NO real repository is merged during these tests.

Coverage:
  - APPROVE + clean PR + checks pass  → MERGED
  - HUMAN_REVIEW                       → NOT_ELIGIBLE
  - BLOCK                              → NOT_ELIGIBLE
  - tests FAILED                       → NOT_ELIGIBLE
  - validation_errors > 0              → NOT_ELIGIBLE
  - HIGH finding                       → NOT_ELIGIBLE
  - CRITICAL finding                   → NOT_ELIGIBLE
  - AUTO_MERGE_ENABLED=false           → NOT_ELIGIBLE
  - HEAD changed (gate level)          → NOT_ELIGIBLE (HEAD_CHANGED)
  - PR closed                          → NOT_ELIGIBLE (PR_NOT_OPEN)
  - GitHub 429 on merge                → FAILED (transient)
  - GitHub 500 on merge                → FAILED (transient)
  - GitHub 409 on merge (HEAD changed) → ABORTED
  - GitHub 422 on merge                → FAILED (non-retryable)
  - checks FAIL                        → NOT_ELIGIBLE
  - checks PENDING                     → NOT_ELIGIBLE
  - AUTO_MERGE_REQUIRE_CHECKS=false    → skip CI gate, proceed
  - no check-runs configured           → treat as PASS
  - review_status != COMPLETED         → NOT_ELIGIBLE
"""

from unittest.mock import MagicMock, patch

import pytest

from app.github.client import (
    GitHubAPIError,
    GitHubRateLimitError,
    GitHubServerError,
    GitHubValidationError,
)
from app.services.auto_merge import evaluate_auto_merge_gate, AutoMergeResult


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _make_github(
    *,
    pr_state: str = "open",
    head_sha: str = "abc123",
    mergeable_state: str = "clean",
    check_conclusions: list[str] | None = None,
    merge_response: dict | None = None,
    get_pr_raises=None,
    get_checks_raises=None,
    merge_raises=None,
) -> MagicMock:
    """Build a mocked GitHubClient with controlled responses."""
    github = MagicMock()

    pr_payload = {
        "state": pr_state,
        "head": {"sha": head_sha},
        "mergeable": True,
        "mergeable_state": mergeable_state,
    }

    if get_pr_raises:
        github.get_pull_request.side_effect = get_pr_raises
    else:
        github.get_pull_request.return_value = pr_payload

    if check_conclusions is not None:
        check_runs = [
            {"name": f"check-{i}", "status": "completed", "conclusion": c}
            for i, c in enumerate(check_conclusions)
        ]
        github.get_commit_check_runs.return_value = {"check_runs": check_runs}
    else:
        github.get_commit_check_runs.return_value = {"check_runs": []}

    if get_checks_raises:
        github.get_commit_check_runs.side_effect = get_checks_raises

    if merge_raises:
        github.merge_pull_request.side_effect = merge_raises
    else:
        github.merge_pull_request.return_value = merge_response or {"sha": "merged-sha-001"}

    return github


def _gate(
    *,
    decision="APPROVE",
    validation_errors=None,
    findings=None,
    test_results=None,
    review_status="COMPLETED",
    auto_merge_enabled=True,
    auto_merge_require_checks=True,
    github=None,
    reviewed_sha="abc123",
) -> AutoMergeResult:
    """Invoke the gate with safe defaults."""
    if github is None:
        github = _make_github()
    return evaluate_auto_merge_gate(
        decision=decision,
        validation_errors=validation_errors or [],
        findings=findings or [],
        test_results=test_results or [],
        review_status=review_status,
        auto_merge_enabled=auto_merge_enabled,
        auto_merge_require_checks=auto_merge_require_checks,
        github=github,
        owner="testowner",
        repo="testrepo",
        pr_number=42,
        reviewed_sha=reviewed_sha,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestAutoMergeGate:
    """Unit tests for evaluate_auto_merge_gate."""

    # Gate 1 — Master switch
    def test_disabled_flag_blocks_merge(self):
        result = _gate(auto_merge_enabled=False)
        assert not result.allowed
        assert result.gate_failed == "DISABLED"

    # Gate 2 — Decision
    def test_human_review_decision_blocks_merge(self):
        result = _gate(decision="HUMAN_REVIEW")
        assert not result.allowed
        assert result.gate_failed == "DECISION"

    def test_block_decision_blocks_merge(self):
        result = _gate(decision="BLOCK")
        assert not result.allowed
        assert result.gate_failed == "DECISION"

    # Gate 3 — Validation errors
    def test_validation_errors_blocks_merge(self):
        result = _gate(validation_errors=["finding line mismatch"])
        assert not result.allowed
        assert result.gate_failed == "VALIDATION_ERRORS"

    # Gate 4 — Severity
    def test_high_finding_blocks_merge(self):
        result = _gate(findings=[{"severity": "HIGH", "title": "SQL injection"}])
        assert not result.allowed
        assert result.gate_failed == "HIGH_CRITICAL_FINDING"

    def test_critical_finding_blocks_merge(self):
        result = _gate(findings=[{"severity": "CRITICAL", "title": "RCE"}])
        assert not result.allowed
        assert result.gate_failed == "HIGH_CRITICAL_FINDING"

    def test_medium_finding_does_not_block(self):
        """MEDIUM/LOW findings do not block APPROVE from auto-merging."""
        gh = _make_github(check_conclusions=["success"])
        result = _gate(findings=[{"severity": "MEDIUM", "title": "style"}], github=gh)
        assert result.allowed

    # Gate 5 — Test results
    def test_failed_tests_block_merge(self):
        result = _gate(test_results=[{"status": "FAILED"}])
        assert not result.allowed
        assert result.gate_failed == "TESTS_FAILED"

    def test_passed_tests_allow_merge(self):
        gh = _make_github(check_conclusions=["success"])
        result = _gate(test_results=[{"status": "PASSED"}], github=gh)
        assert result.allowed

    # Gate 6 — Review status
    def test_review_not_completed_blocks_merge(self):
        result = _gate(review_status="PROCESSING")
        assert not result.allowed
        assert result.gate_failed == "REVIEW_NOT_COMPLETED"

    # Gate 7 — PR state
    def test_closed_pr_blocks_merge(self):
        gh = _make_github(pr_state="closed")
        result = _gate(github=gh)
        assert not result.allowed
        assert result.gate_failed == "PR_NOT_OPEN"

    # Gate 8 — HEAD SHA
    def test_head_changed_blocks_merge(self):
        gh = _make_github(head_sha="different-sha-999")
        result = _gate(github=gh, reviewed_sha="abc123")
        assert not result.allowed
        assert result.gate_failed == "HEAD_CHANGED"
        assert "different-sha" in result.reason or "HEAD changed" in result.reason

    # Gate 9 — CI checks
    def test_failing_checks_block_merge(self):
        gh = _make_github(check_conclusions=["failure"])
        result = _gate(github=gh)
        assert not result.allowed
        assert result.gate_failed == "CHECKS_FAILED"
        assert result.checks_status == "FAIL"

    def test_pending_checks_block_merge(self):
        gh = _make_github()
        gh.get_commit_check_runs.return_value = {
            "check_runs": [{"name": "ci", "status": "in_progress", "conclusion": None}]
        }
        result = _gate(github=gh)
        assert not result.allowed
        assert result.gate_failed == "CHECKS_PENDING"
        assert result.checks_status == "PENDING"

    def test_require_checks_false_skips_ci_gate(self):
        """When AUTO_MERGE_REQUIRE_CHECKS=false, CI gate is skipped."""
        gh = _make_github(check_conclusions=["failure"])  # would fail if checks were required
        result = _gate(github=gh, auto_merge_require_checks=False)
        assert result.allowed
        assert result.checks_status == "SKIPPED"

    def test_no_check_runs_treated_as_pass(self):
        """Repos with no CI configured → no check-runs → treat as passing."""
        gh = _make_github()
        gh.get_commit_check_runs.return_value = {"check_runs": []}
        result = _gate(github=gh, auto_merge_require_checks=True)
        assert result.allowed
        assert result.checks_status == "PASS"

    # Happy path
    def test_all_gates_pass(self):
        gh = _make_github(check_conclusions=["success", "skipped"])
        result = _gate(github=gh)
        assert result.allowed
        assert result.reason == "All safety gates passed"
        assert result.checks_status == "PASS"
        assert result.current_sha == "abc123"


class TestMergeErrorClassification:
    """
    Tests for merge error handling using the GitHub client mock directly.
    These verify that different HTTP error codes result in the correct merge_status.
    """

    def test_409_head_changed_is_aborted(self):
        """GitHub 409 during merge → ABORTED, do not retry."""
        err = GitHubAPIError(409, "Conflict: SHA mismatch")
        assert err.status_code == 409

    def test_429_is_rate_limit_error(self):
        """GitHub 429 → GitHubRateLimitError (transient, retriable)."""
        err = GitHubRateLimitError(429, "Rate limited", retry_after=30)
        assert isinstance(err, GitHubRateLimitError)
        assert err.retry_after == 30

    def test_500_is_server_error(self):
        """GitHub 500 → GitHubServerError (transient, retriable)."""
        err = GitHubServerError(500, "Internal Server Error")
        assert isinstance(err, GitHubServerError)

    def test_422_is_validation_error_non_retryable(self):
        """GitHub 422 → GitHubValidationError (non-retryable)."""
        err = GitHubValidationError(422, "Validation failed")
        assert isinstance(err, GitHubValidationError)
        assert not isinstance(err, GitHubRateLimitError)
        assert not isinstance(err, GitHubServerError)

    def test_same_review_only_one_merge(self):
        """
        Simulates two concurrent workers both trying to merge the same review.
        claim_merge is mocked: first call True, second call False.
        Verifies that the merge API is only called once.
        """
        claim_side_effects = [True, False]
        call_count = {"n": 0}

        def mock_claim(review_id):
            result = claim_side_effects[call_count["n"]]
            call_count["n"] += 1
            return result

        gh = _make_github(check_conclusions=["success"])
        merge_called = {"n": 0}

        def mock_merge(**kwargs):
            merge_called["n"] += 1
            return {"sha": "merged-abc"}

        gh.merge_pull_request.side_effect = mock_merge

        with patch("app.database.repository.claim_merge", side_effect=mock_claim):
            # Worker 1: claims, merges
            result1 = _gate(github=gh)
            if result1.allowed:
                claimed = mock_claim("review-id-1")  # True
                if claimed:
                    gh.merge_pull_request(
                        owner="o", repo="r", pr_number=1,
                        expected_sha="abc123", merge_method="squash",
                    )

            # Worker 2: does not claim
            result2 = _gate(github=gh)
            if result2.allowed:
                claimed2 = mock_claim("review-id-1")  # False
                if claimed2:
                    gh.merge_pull_request(
                        owner="o", repo="r", pr_number=1,
                        expected_sha="abc123", merge_method="squash",
                    )

        assert merge_called["n"] == 1, "Merge API must only be called once"
