"""
Phase 10.1 — Unit tests for TestResult contract.

Zero external calls. Pure model validation.
"""

import json

import pytest
from pydantic import ValidationError

from app.models.test_results import TestResult


# ---------------------------------------------------------------------------
# Happy-path tests
# ---------------------------------------------------------------------------

def test_passed_minimal():
    r = TestResult(status="PASSED")
    assert r.status == "PASSED"
    assert r.exit_code is None
    assert r.stdout == ""
    assert r.stderr == ""
    assert r.duration_seconds == 0.0
    assert r.tests_total is None
    assert r.tests_passed is None
    assert r.tests_failed is None
    assert r.tests_skipped is None
    assert r.failure_summary == []
    assert r.framework is None
    assert r.command is None


def test_failed_with_counts():
    r = TestResult(
        status="FAILED",
        framework="pytest",
        command="python -m pytest -q",
        exit_code=1,
        stdout="FAILED test_foo.py::test_bar\n1 failed in 0.5s",
        duration_seconds=0.5,
        tests_total=4,
        tests_passed=3,
        tests_failed=1,
        tests_skipped=0,
        failure_summary=["FAILED test_foo.py::test_bar"],
    )
    assert r.status == "FAILED"
    assert r.tests_failed == 1
    assert r.tests_total == 4
    assert len(r.failure_summary) == 1


def test_timeout():
    r = TestResult(
        status="TIMEOUT",
        duration_seconds=30.0,
    )
    assert r.status == "TIMEOUT"
    assert r.exit_code is None


def test_not_run():
    r = TestResult(status="NOT_RUN")
    assert r.status == "NOT_RUN"


def test_error():
    r = TestResult(
        status="ERROR",
        stderr="pytest not found",
    )
    assert r.status == "ERROR"
    assert r.stderr == "pytest not found"


# ---------------------------------------------------------------------------
# JSON round-trip
# ---------------------------------------------------------------------------

def test_json_round_trip():
    r = TestResult(
        status="FAILED",
        framework="pytest",
        exit_code=1,
        tests_total=2,
        tests_failed=1,
        failure_summary=["FAILED tests/test_x.py::test_y"],
    )
    dumped = r.model_dump()
    restored = TestResult(**dumped)
    assert restored.status == r.status
    assert restored.failure_summary == r.failure_summary

    # Also verify JSON serialization works (for DB / LangGraph state).
    raw_json = r.model_dump_json()
    parsed = json.loads(raw_json)
    assert parsed["status"] == "FAILED"


# ---------------------------------------------------------------------------
# Validation — invalid status must be rejected
# ---------------------------------------------------------------------------

def test_invalid_status_rejected():
    with pytest.raises(ValidationError):
        TestResult(status="UNKNOWN_INVALID")


def test_invalid_status_empty_rejected():
    with pytest.raises(ValidationError):
        TestResult(status="")
