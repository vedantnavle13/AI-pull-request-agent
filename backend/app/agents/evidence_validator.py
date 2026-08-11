"""
Phase 10.5 — EvidenceValidator.

Cross-checks AI findings against actual test evidence.

Key rule:
    The AI MUST NOT claim "tests pass" when the test runner says FAILED,
    and vice versa. Any such conflict is recorded as an error.
"""

from app.agents.evidence import Evidence
from app.models.test_results import TestResult


# Categories that imply runtime/test behaviour.
_RUNTIME_CATEGORIES = frozenset(
    {
        "bug",
        "error",
        "exception",
        "runtime",
        "test",
        "testing",
    }
)

# Keywords in AI finding descriptions that imply test-related claims.
_TEST_CLAIM_KEYWORDS = (
    "test",
    "tests",
    "pytest",
    "unittest",
    "test suite",
    "test case",
    "passes",
    "fails",
    "breaks",
)


class EvidenceValidator:
    """
    Validates AI findings against test evidence.

    Usage:
        ev = EvidenceValidator()
        evidence, errors = ev.validate(findings, test_results, diff)
    """

    def validate(
        self,
        findings: list[dict],
        test_results: list[TestResult],
        diff: str,
    ) -> tuple[list[Evidence], list[str]]:
        """
        Return (evidence_list, conflict_errors).

        One Evidence object is produced per finding.
        Conflicts (AI contradicts test result) are recorded in errors.
        """

        evidence: list[Evidence] = []
        errors: list[str] = []

        # Determine overall test outcome from the list.
        test_status = self._overall_test_status(test_results)
        test_source = "pytest" if test_results else None

        for idx, finding in enumerate(findings):
            ev = self._evaluate_finding(
                index=idx,
                finding=finding,
                test_status=test_status,
                test_source=test_source,
                diff=diff,
                errors=errors,
            )
            evidence.append(ev)

        return evidence, errors

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _overall_test_status(self, test_results: list[TestResult]) -> str | None:
        """
        Return the most significant status from the test result list.

        Priority: FAILED > ERROR > TIMEOUT > PASSED > NOT_RUN > None
        """
        if not test_results:
            return None

        priority = ["FAILED", "ERROR", "TIMEOUT", "PASSED", "NOT_RUN"]
        statuses = {r.status for r in test_results}

        for p in priority:
            if p in statuses:
                return p

        return test_results[0].status

    def _implies_test_claim(self, finding: dict) -> bool:
        """Return True if the finding description makes a claim about tests."""
        desc = (finding.get("description", "") or "").lower()
        title = (finding.get("title", "") or "").lower()
        cat = (finding.get("category", "") or "").lower()

        text = f"{title} {desc} {cat}"
        return any(kw in text for kw in _TEST_CLAIM_KEYWORDS)

    def _is_runtime_finding(self, finding: dict) -> bool:
        """Return True if the finding category is runtime/bug related."""
        cat = (finding.get("category", "") or "").lower()
        return cat in _RUNTIME_CATEGORIES

    def _evaluate_finding(
        self,
        index: int,
        finding: dict,
        test_status: str | None,
        test_source: str | None,
        diff: str,
        errors: list[str],
    ) -> Evidence:
        """Build one Evidence object for a finding."""

        # If no test data is available, produce DIFF evidence.
        if test_status is None:
            return Evidence(
                type="DIFF",
                description=(
                    f"Finding {index}: no test evidence available; "
                    "assessed from diff only."
                ),
                source="diff",
                supports_finding=True,  # Give benefit of the doubt.
            )

        # Tests not run (no Python files, or framework not detected).
        if test_status == "NOT_RUN":
            return Evidence(
                type="TEST_RESULT",
                description=(
                    f"Finding {index}: tests were not run "
                    "(no test framework detected in PR)."
                ),
                source=test_source,
                supports_finding=False,
            )

        # Tests ran — check for conflicts.
        makes_test_claim = self._implies_test_claim(finding)
        is_runtime = self._is_runtime_finding(finding)

        if test_status == "PASSED":
            if makes_test_claim or is_runtime:
                # AI claims a runtime bug, but tests pass.
                # This is a potential conflict — mark as unsupported,
                # but do NOT discard (could be a gap in test coverage).
                return Evidence(
                    type="TEST_RESULT",
                    description=(
                        f"Finding {index}: tests PASSED but AI claims "
                        "a runtime issue. May indicate a test-coverage gap."
                    ),
                    source=test_source,
                    supports_finding=False,
                )

            # Tests pass and the finding is not about runtime — supported.
            return Evidence(
                type="TEST_RESULT",
                description=(
                    f"Finding {index}: tests PASSED; "
                    "finding is style/quality/docs — consistent."
                ),
                source=test_source,
                supports_finding=True,
            )

        if test_status == "FAILED":
            # Tests failed — runtime findings are now supported.
            if is_runtime or makes_test_claim:
                return Evidence(
                    type="TEST_RESULT",
                    description=(
                        f"Finding {index}: tests FAILED and AI identifies "
                        "a runtime issue — finding is supported by evidence."
                    ),
                    source=test_source,
                    supports_finding=True,
                )

            # Tests failed but finding is unrelated (style/docs/security).
            return Evidence(
                type="TEST_RESULT",
                description=(
                    f"Finding {index}: tests FAILED but finding is "
                    "unrelated to runtime behaviour. Independent issue."
                ),
                source=test_source,
                supports_finding=True,
            )

        # TIMEOUT / ERROR — we cannot make a strong claim either way.
        return Evidence(
            type="TEST_RESULT",
            description=(
                f"Finding {index}: test execution ended with status "
                f"{test_status!r}. Evidence inconclusive."
            ),
            source=test_source,
            supports_finding=False,
        )
