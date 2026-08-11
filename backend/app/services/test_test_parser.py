"""
Phase 10.4 — Unit tests for test_parser.py.

Pure string parsing — no subprocess, no Gemini calls.
"""

from app.services.test_parser import parse_pytest_output


# ---------------------------------------------------------------------------
# All passed
# ---------------------------------------------------------------------------

def test_all_passed():
    stdout = """\
test_foo.py::test_a PASSED
test_foo.py::test_b PASSED
test_foo.py::test_c PASSED
========================= 3 passed in 1.20s =========================
"""
    r = parse_pytest_output(stdout=stdout, stderr="", exit_code=0, duration_seconds=1.2)
    assert r.status == "PASSED"
    assert r.tests_passed == 3
    assert r.tests_total == 3
    assert r.tests_failed is None or r.tests_failed == 0
    assert r.duration_seconds == 1.20


# ---------------------------------------------------------------------------
# Mixed passed / failed
# ---------------------------------------------------------------------------

def test_mixed_pass_fail():
    stdout = """\
FAILED test_foo.py::test_bad - AssertionError: 0 != 1
========================= 1 failed, 3 passed in 2.41s =========================
"""
    r = parse_pytest_output(stdout=stdout, stderr="", exit_code=1, duration_seconds=2.41)
    assert r.status == "FAILED"
    assert r.tests_passed == 3
    assert r.tests_failed == 1
    assert r.tests_total == 4
    assert "FAILED test_foo.py::test_bad" in r.failure_summary[0]


# ---------------------------------------------------------------------------
# Only failures
# ---------------------------------------------------------------------------

def test_all_failed():
    stdout = """\
FAILED test_foo.py::test_a
FAILED test_foo.py::test_b
========================= 2 failed in 0.50s =========================
"""
    r = parse_pytest_output(stdout=stdout, stderr="", exit_code=1, duration_seconds=0.5)
    assert r.status == "FAILED"
    assert r.tests_failed == 2
    assert len(r.failure_summary) == 2


# ---------------------------------------------------------------------------
# No tests collected
# ---------------------------------------------------------------------------

def test_no_tests_found():
    stdout = "collected 0 items\n"
    r = parse_pytest_output(stdout=stdout, stderr="", exit_code=5, duration_seconds=0.1)
    assert r.status == "NOT_RUN"


def test_no_tests_ran_text():
    stdout = "no tests ran\n"
    r = parse_pytest_output(stdout=stdout, stderr="", exit_code=5, duration_seconds=0.1)
    assert r.status == "NOT_RUN"


# ---------------------------------------------------------------------------
# Collection errors
# ---------------------------------------------------------------------------

def test_collection_error():
    stderr = "ERROR collecting tests/test_bad.py\nImportError: No module named 'missing'\n"
    r = parse_pytest_output(stdout="", stderr=stderr, exit_code=2, duration_seconds=0.2)
    assert r.status == "ERROR"


# ---------------------------------------------------------------------------
# Empty output (fallback to exit code)
# ---------------------------------------------------------------------------

def test_empty_output_exit_0():
    r = parse_pytest_output(stdout="", stderr="", exit_code=0, duration_seconds=0.0)
    assert r.status == "PASSED"


def test_empty_output_exit_nonzero():
    r = parse_pytest_output(stdout="", stderr="", exit_code=1, duration_seconds=0.0)
    assert r.status == "FAILED"


# ---------------------------------------------------------------------------
# Skipped tests included in totals
# ---------------------------------------------------------------------------

def test_skipped():
    stdout = "========================= 2 passed, 1 skipped in 1.00s =========================\n"
    r = parse_pytest_output(stdout=stdout, stderr="", exit_code=0, duration_seconds=1.0)
    assert r.status == "PASSED"
    assert r.tests_skipped == 1
    assert r.tests_passed == 2


# ---------------------------------------------------------------------------
# Warnings in summary line (common pytest output)
# ---------------------------------------------------------------------------

def test_with_warnings_in_summary():
    stdout = "========================= 3 passed, 2 warnings in 0.80s =========================\n"
    r = parse_pytest_output(stdout=stdout, stderr="", exit_code=0, duration_seconds=0.8)
    assert r.status == "PASSED"
    assert r.tests_passed == 3
