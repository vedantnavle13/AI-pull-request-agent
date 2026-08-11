"""
Phase 10.4 — TestParser.

Converts raw pytest / unittest stdout into a structured TestResult.
Does NOT execute any process; pure string parsing.
"""

import re
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Intermediate result (not exposed outside this module)
# ---------------------------------------------------------------------------

@dataclass
class _ParsedOutput:
    status: str
    tests_total: int | None = None
    tests_passed: int | None = None
    tests_failed: int | None = None
    tests_skipped: int | None = None
    duration_seconds: float = 0.0
    failure_summary: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Regex patterns for pytest summary line
# ---------------------------------------------------------------------------

# Detect the summary line itself (the "=== N ... in X.XXs ===" line).
_SUMMARY_LINE_RE = re.compile(
    r"=+\s+(.*?)\s+in\s+([\d.]+)s\s+=+",
    re.IGNORECASE,
)

# Individual count patterns (order-independent within the summary line).
_PASSED_RE  = re.compile(r"(\d+)\s+passed",  re.IGNORECASE)
_FAILED_RE  = re.compile(r"(\d+)\s+failed",  re.IGNORECASE)
_ERROR_RE   = re.compile(r"(\d+)\s+error",   re.IGNORECASE)
_SKIPPED_RE = re.compile(r"(\d+)\s+skipped", re.IGNORECASE)


# e.g. "FAILED tests/test_foo.py::test_bar - AssertionError"
_FAILED_LINE_RE = re.compile(r"^FAILED\s+\S+", re.MULTILINE)

# Detect no-tests outcome
_NO_TESTS_RE = re.compile(
    r"no tests ran|collected 0 items",
    re.IGNORECASE,
)

# Detect collection errors
_COLLECTION_ERROR_RE = re.compile(
    r"ERROR collecting|ImportError|SyntaxError",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Public function
# ---------------------------------------------------------------------------

def parse_pytest_output(
    stdout: str,
    stderr: str,
    exit_code: int | None,
    duration_seconds: float = 0.0,
) -> _ParsedOutput:
    """
    Parse raw pytest output and return a _ParsedOutput.

    Handles:
    - All tests passed
    - Some tests failed
    - Collection errors / import errors / syntax errors
    - No tests found
    - Timeout (caller passes status directly; this function is not called)
    - Empty output
    """

    combined = stdout + "\n" + stderr

    # --- Collection / import / syntax errors ---
    if _COLLECTION_ERROR_RE.search(combined) and exit_code not in (0, 1):
        return _ParsedOutput(
            status="ERROR",
            duration_seconds=duration_seconds,
            failure_summary=_extract_failure_lines(stdout),
        )

    # --- No tests ran ---
    if _NO_TESTS_RE.search(combined) or (not combined.strip() and exit_code == 5):
        return _ParsedOutput(
            status="NOT_RUN",
            duration_seconds=duration_seconds,
        )

    # --- Try to parse pytest summary line ---
    line_match = _SUMMARY_LINE_RE.search(combined)

    if line_match:
        summary_text = line_match.group(1)
        dur_str      = line_match.group(2)
        dur = float(dur_str) if dur_str else duration_seconds

        passed  = _to_int(m.group(1)) if (m := _PASSED_RE.search(summary_text)) else None
        failed  = _to_int(m.group(1)) if (m := _FAILED_RE.search(summary_text))  else None
        errored = _to_int(m.group(1)) if (m := _ERROR_RE.search(summary_text))   else None
        skipped = _to_int(m.group(1)) if (m := _SKIPPED_RE.search(summary_text)) else None

        total_failed = (failed or 0) + (errored or 0)
        total = (passed or 0) + total_failed + (skipped or 0)

        status = "PASSED" if total_failed == 0 else "FAILED"

        return _ParsedOutput(
            status=status,
            tests_total=total if total > 0 else None,
            tests_passed=passed,
            tests_failed=total_failed if total_failed > 0 else None,
            tests_skipped=skipped,
            duration_seconds=dur,
            failure_summary=_extract_failure_lines(stdout),
        )


    # --- Fallback: rely on exit code ---
    if exit_code == 0:
        return _ParsedOutput(
            status="PASSED",
            duration_seconds=duration_seconds,
        )

    if exit_code is not None and exit_code > 0:
        return _ParsedOutput(
            status="FAILED",
            duration_seconds=duration_seconds,
            failure_summary=_extract_failure_lines(stdout),
        )

    # Could not determine outcome.
    return _ParsedOutput(
        status="ERROR",
        duration_seconds=duration_seconds,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _to_int(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _extract_failure_lines(stdout: str) -> list[str]:
    """Return lines that start with 'FAILED ' from pytest -v output."""
    return [
        line.strip()
        for line in _FAILED_LINE_RE.findall(stdout)
    ]
