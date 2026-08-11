"""
Phase 10.2 — Unit tests for the Evidence contract.
Zero external calls.
"""

import json

import pytest
from pydantic import ValidationError

from app.agents.evidence import Evidence


def test_evidence_defaults():
    e = Evidence(
        type="TEST_RESULT",
        description="Tests failed with exit code 1.",
    )
    assert e.type == "TEST_RESULT"
    assert e.description == "Tests failed with exit code 1."
    assert e.source is None
    assert e.supports_finding is False


def test_evidence_full():
    e = Evidence(
        type="DIFF",
        description="Division by zero visible in diff.",
        source="diff:addition.py:6",
        supports_finding=True,
    )
    assert e.supports_finding is True
    assert e.source == "diff:addition.py:6"


def test_all_valid_types():
    for t in ("TEST_RESULT", "STATIC_ANALYSIS", "DIFF", "FILE", "UNKNOWN"):
        e = Evidence(type=t, description="ok")
        assert e.type == t


def test_invalid_type_rejected():
    with pytest.raises(ValidationError):
        Evidence(type="BAD_TYPE", description="x")


def test_missing_description_rejected():
    with pytest.raises(ValidationError):
        Evidence(type="FILE")


def test_json_round_trip():
    e = Evidence(
        type="TEST_RESULT",
        description="pytest returned exit code 1",
        source="pytest",
        supports_finding=True,
    )
    raw = e.model_dump_json()
    restored = Evidence(**json.loads(raw))
    assert restored.type == e.type
    assert restored.supports_finding == e.supports_finding
