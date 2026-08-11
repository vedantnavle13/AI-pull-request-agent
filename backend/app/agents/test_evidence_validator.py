"""
Phase 10.5 — Unit tests for EvidenceValidator.

No Gemini calls. No subprocess calls.
"""

from app.agents.evidence_validator import EvidenceValidator
from app.models.test_results import TestResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_finding(
    title: str = "Some finding",
    description: str = "A problem was found.",
    category: str = "quality",
    severity: str = "MEDIUM",
    file: str = "main.py",
    line: int = 1,
) -> dict:
    return {
        "title": title,
        "description": description,
        "category": category,
        "severity": severity,
        "file": file,
        "line": line,
    }


def _make_test_result(status: str) -> TestResult:
    return TestResult(status=status)


# ---------------------------------------------------------------------------
# No test data available
# ---------------------------------------------------------------------------

def test_no_test_data_produces_diff_evidence():
    ev = EvidenceValidator()
    findings = [_make_finding()]
    evidence, errors = ev.validate(findings, [], diff="")
    assert len(evidence) == 1
    assert evidence[0].type == "DIFF"
    assert evidence[0].supports_finding is True
    assert errors == []


# ---------------------------------------------------------------------------
# NOT_RUN (no framework detected)
# ---------------------------------------------------------------------------

def test_not_run_produces_unsupported_evidence():
    ev = EvidenceValidator()
    findings = [_make_finding()]
    results = [_make_test_result("NOT_RUN")]
    evidence, errors = ev.validate(findings, results, diff="")
    assert evidence[0].type == "TEST_RESULT"
    assert evidence[0].supports_finding is False


# ---------------------------------------------------------------------------
# Tests PASSED — runtime finding (potential conflict)
# ---------------------------------------------------------------------------

def test_passed_with_runtime_finding_is_unsupported():
    ev = EvidenceValidator()
    finding = _make_finding(
        title="Potential ZeroDivisionError",
        description="This will crash at runtime.",
        category="bug",
    )
    results = [_make_test_result("PASSED")]
    evidence, errors = ev.validate([finding], results, diff="")
    assert evidence[0].type == "TEST_RESULT"
    # Tests pass but AI claims runtime bug → not directly supported.
    assert evidence[0].supports_finding is False


# ---------------------------------------------------------------------------
# Tests PASSED — style/quality finding (no conflict)
# ---------------------------------------------------------------------------

def test_passed_with_style_finding_is_supported():
    ev = EvidenceValidator()
    finding = _make_finding(
        title="Missing docstring",
        description="Function lacks documentation.",
        category="quality",
    )
    results = [_make_test_result("PASSED")]
    evidence, errors = ev.validate([finding], results, diff="")
    assert evidence[0].supports_finding is True


# ---------------------------------------------------------------------------
# Tests FAILED — runtime finding is supported
# ---------------------------------------------------------------------------

def test_failed_with_runtime_finding_is_supported():
    ev = EvidenceValidator()
    finding = _make_finding(
        title="Division by zero",
        description="Tests fail because of this bug.",
        category="bug",
    )
    results = [_make_test_result("FAILED")]
    evidence, errors = ev.validate([finding], results, diff="")
    assert evidence[0].supports_finding is True


# ---------------------------------------------------------------------------
# Tests FAILED — unrelated finding is still kept
# ---------------------------------------------------------------------------

def test_failed_with_unrelated_finding_still_accepted():
    ev = EvidenceValidator()
    finding = _make_finding(
        title="Hardcoded API key",
        description="Security issue: key in source.",
        category="security",
    )
    results = [_make_test_result("FAILED")]
    evidence, errors = ev.validate([finding], results, diff="")
    assert evidence[0].type == "TEST_RESULT"
    # Security finding accepted even though tests failed.
    assert evidence[0].supports_finding is True


# ---------------------------------------------------------------------------
# TIMEOUT / ERROR — inconclusive
# ---------------------------------------------------------------------------

def test_timeout_is_inconclusive():
    ev = EvidenceValidator()
    findings = [_make_finding()]
    results = [_make_test_result("TIMEOUT")]
    evidence, errors = ev.validate(findings, results, diff="")
    assert evidence[0].supports_finding is False


def test_error_is_inconclusive():
    ev = EvidenceValidator()
    findings = [_make_finding()]
    results = [_make_test_result("ERROR")]
    evidence, errors = ev.validate(findings, results, diff="")
    assert evidence[0].supports_finding is False


# ---------------------------------------------------------------------------
# Multiple findings produce one evidence per finding
# ---------------------------------------------------------------------------

def test_multiple_findings_produce_one_evidence_each():
    ev = EvidenceValidator()
    findings = [_make_finding(title=f"Issue {i}") for i in range(5)]
    results = [_make_test_result("PASSED")]
    evidence, errors = ev.validate(findings, results, diff="")
    assert len(evidence) == 5


# ---------------------------------------------------------------------------
# Empty findings list
# ---------------------------------------------------------------------------

def test_empty_findings():
    ev = EvidenceValidator()
    evidence, errors = ev.validate([], [_make_test_result("PASSED")], diff="")
    assert evidence == []
    assert errors == []
