"""
Phase 13 — Deterministic Auto-Merge Gate.

This module contains ONLY deterministic logic — no LLM calls.
The gate evaluates a fixed set of conditions and decides whether
auto-merge is allowed. The GitHub merge API is called by the worker,
NOT by this module.

Gate conditions (ALL must pass):
  1. AUTO_MERGE_ENABLED == True
  2. decision == "APPROVE"
  3. validation_errors == 0
  4. No finding with severity HIGH or CRITICAL
  5. No test result with status FAILED
  6. review_status == "COMPLETED"
  7. PR is still OPEN
  8. current PR head SHA == reviewed commit SHA (HEAD_CHANGED guard)
  9. (if AUTO_MERGE_REQUIRE_CHECKS) all CI check-runs are success/skipped
"""

import logging
from dataclasses import dataclass, field

from app.github.client import GitHubClient, GitHubAPIError

logger = logging.getLogger(__name__)

# Findings that block auto-merge.
_BLOCKING_SEVERITIES = {"HIGH", "CRITICAL"}

# Check-run conclusions that are acceptable.
_PASSING_CONCLUSIONS = {"success", "skipped", "neutral"}

# Check-run statuses that mean "not yet complete" — abort, do not merge.
_PENDING_STATUSES = {"queued", "in_progress"}


@dataclass
class AutoMergeResult:
    """Result of the auto-merge gate evaluation."""
    allowed: bool
    reason: str                         # Human-readable explanation
    checks_status: str = "SKIPPED"      # PASS | FAIL | SKIPPED | PENDING
    current_sha: str = ""               # Re-fetched PR head SHA at gate time
    gate_failed: str = ""               # Which specific gate failed


def evaluate_auto_merge_gate(
    *,
    decision: str,
    validation_errors: list,
    findings: list,
    test_results: list,
    review_status: str,
    auto_merge_enabled: bool,
    auto_merge_require_checks: bool,
    github: GitHubClient,
    owner: str,
    repo: str,
    pr_number: int,
    reviewed_sha: str,
) -> AutoMergeResult:
    """
    Evaluate all auto-merge safety gates in order.

    Returns AutoMergeResult with allowed=True only when every gate passes.
    The caller is responsible for calling github.merge_pull_request() if allowed.
    """

    # Gate 1 — Master switch
    if not auto_merge_enabled:
        return AutoMergeResult(
            allowed=False,
            reason="AUTO_MERGE_ENABLED is false",
            gate_failed="DISABLED",
        )

    # Gate 2 — Policy decision
    if decision != "APPROVE":
        return AutoMergeResult(
            allowed=False,
            reason=f"Policy decision is {decision!r}, not APPROVE",
            gate_failed="DECISION",
        )

    # Gate 3 — Validation errors
    if validation_errors:
        return AutoMergeResult(
            allowed=False,
            reason=f"{len(validation_errors)} validation error(s) present",
            gate_failed="VALIDATION_ERRORS",
        )

    # Gate 4 — No HIGH/CRITICAL findings
    blocking = [
        f for f in findings
        if (f.get("severity") or "").upper() in _BLOCKING_SEVERITIES
    ]
    if blocking:
        titles = ", ".join(f.get("title", "?") for f in blocking[:3])
        return AutoMergeResult(
            allowed=False,
            reason=f"Blocking finding(s): {titles}",
            gate_failed="HIGH_CRITICAL_FINDING",
        )

    # Gate 5 — Test results
    failed_tests = [
        t for t in test_results
        if (t.get("status") or "").upper() == "FAILED"
    ]
    if failed_tests:
        return AutoMergeResult(
            allowed=False,
            reason=f"{len(failed_tests)} test suite(s) failed",
            gate_failed="TESTS_FAILED",
        )

    # Gate 6 — Review must be COMPLETED
    if review_status != "COMPLETED":
        return AutoMergeResult(
            allowed=False,
            reason=f"Review status is {review_status!r}, not COMPLETED",
            gate_failed="REVIEW_NOT_COMPLETED",
        )

    # Gates 7 & 8 — Live GitHub PR state check
    try:
        pr = github.get_pull_request(owner=owner, repo=repo, pr_number=pr_number)
    except GitHubAPIError as exc:
        return AutoMergeResult(
            allowed=False,
            reason=f"Failed to fetch PR state: {exc}",
            gate_failed="GITHUB_FETCH_ERROR",
        )

    pr_state = pr.get("state", "unknown")
    current_sha = pr.get("head", {}).get("sha", "")

    # Gate 7 — PR must still be open
    if pr_state != "open":
        return AutoMergeResult(
            allowed=False,
            reason=f"PR is {pr_state!r}, not open",
            current_sha=current_sha,
            gate_failed="PR_NOT_OPEN",
        )

    # Gate 8 — HEAD SHA must not have changed (critical security gate)
    if current_sha != reviewed_sha:
        logger.warning(
            "[AutoMerge] HEAD changed for PR #%d: reviewed=%s current=%s",
            pr_number, reviewed_sha[:8], current_sha[:8],
        )
        return AutoMergeResult(
            allowed=False,
            reason=(
                f"HEAD changed after review: "
                f"reviewed={reviewed_sha[:8]!r} current={current_sha[:8]!r}"
            ),
            current_sha=current_sha,
            gate_failed="HEAD_CHANGED",
        )

    # Gate 9 — CI Check-runs (optional)
    checks_status = "SKIPPED"
    if auto_merge_require_checks:
        try:
            checks_data = github.get_commit_check_runs(
                owner=owner, repo=repo, commit_sha=reviewed_sha
            )
            check_runs = checks_data.get("check_runs", [])

            if check_runs:
                pending = [
                    r for r in check_runs
                    if r.get("status") in _PENDING_STATUSES
                ]
                if pending:
                    pending_names = ", ".join(r.get("name", "?") for r in pending[:3])
                    return AutoMergeResult(
                        allowed=False,
                        reason=f"CI checks still pending: {pending_names}",
                        current_sha=current_sha,
                        checks_status="PENDING",
                        gate_failed="CHECKS_PENDING",
                    )

                failing = [
                    r for r in check_runs
                    if r.get("conclusion") not in _PASSING_CONCLUSIONS
                    and r.get("conclusion") is not None
                ]
                if failing:
                    failing_names = ", ".join(r.get("name", "?") for r in failing[:3])
                    return AutoMergeResult(
                        allowed=False,
                        reason=f"CI check(s) failed: {failing_names}",
                        current_sha=current_sha,
                        checks_status="FAIL",
                        gate_failed="CHECKS_FAILED",
                    )

                checks_status = "PASS"
            else:
                # No check-runs configured — treat as PASS
                checks_status = "PASS"

        except GitHubAPIError as exc:
            return AutoMergeResult(
                allowed=False,
                reason=f"Failed to fetch check-runs: {exc}",
                current_sha=current_sha,
                checks_status="ERROR",
                gate_failed="CHECKS_FETCH_ERROR",
            )

    # All gates passed
    logger.info(
        "[AutoMerge] All gates passed for PR #%d SHA=%s checks=%s",
        pr_number, reviewed_sha[:8], checks_status,
    )
    return AutoMergeResult(
        allowed=True,
        reason="All safety gates passed",
        current_sha=current_sha,
        checks_status=checks_status,
        gate_failed="",
    )
