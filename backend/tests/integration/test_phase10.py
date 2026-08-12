"""
Phase 10.9 — Integration test.

Tests the complete Phase 10 pipeline end-to-end:

    Fake PR state
        ↓
    Mock checkout  (temp dir with a real Python file)
        ↓
    Mock TestRunner  (controlled TestResult)
        ↓
    Mock Gemini agents  (controlled AgentResult)
        ↓
    Real ReviewValidator
    Real EvidenceValidator
    Real final_decision (via LangGraph)
        ↓
    Assertions on result keys + decision logic

Zero real Gemini API calls.
Zero real GitHub API calls.
Zero real git operations.

NOTE: All graph tests use ainvoke() because agent nodes are now async def
(they use asyncio.to_thread() for true parallel execution).
"""

import os
import tempfile
from unittest.mock import MagicMock, patch

import pytest

from app.agents.contracts import AgentResult, Finding
from app.models.test_results import TestResult
from app.orchestrator.graph import build_review_graph


# ---------------------------------------------------------------------------
# Shared test data
# ---------------------------------------------------------------------------

def _make_finding(
    title: str = "Hardcoded secret",
    description: str = "API key found in source.",
    severity: str = "HIGH",
    category: str = "security",
    file: str = "main.py",
    line: int = 1,
    suggestion: str = "Use environment variables.",
) -> Finding:
    return Finding(
        title=title,
        description=description,
        severity=severity,
        category=category,
        file=file,
        line=line,
        suggestion=suggestion,
    )


def _agent_result(findings: list[Finding], agent: str = "security") -> AgentResult:
    return AgentResult(agent=agent, findings=findings)


def _mock_agent(result: AgentResult) -> MagicMock:
    m = MagicMock()
    m.review.return_value = result
    return m


# ---------------------------------------------------------------------------
# Test 1: HIGH finding + PASSED tests → HUMAN_REVIEW
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_integration_high_finding_tests_pass():
    """
    HIGH severity finding + PASSED tests → HUMAN_REVIEW.
    Evidence validator marks the finding as present.
    """

    security_result = _agent_result(
        [_make_finding(severity="HIGH", file="main.py")],
        agent="security",
    )
    empty = _agent_result([], agent="stub")

    mock_sec   = _mock_agent(security_result)
    mock_qual  = _mock_agent(empty)
    mock_tests = _mock_agent(empty)
    mock_docs  = _mock_agent(empty)

    with (
        patch("app.orchestrator.nodes.security_agent", mock_sec),
        patch("app.orchestrator.nodes.quality_agent",  mock_qual),
        patch("app.orchestrator.nodes.test_agent",     mock_tests),
        patch("app.orchestrator.nodes.docs_agent",     mock_docs),
    ):
        graph = build_review_graph()

        result = await graph.ainvoke({
            "installation_id": 1,
            "owner": "test",
            "repo": "demo",
            "pr_number": 1,
            "commit_sha": "abc123",
            "diff": "print('hello')",
            "files": [{"filename": "main.py"}],
            "test_results": [{"status": "PASSED"}],
        })

    _assert_required_keys(result)
    assert result["decision"] == "HUMAN_REVIEW"
    assert len(result["findings"]) == 1
    assert len(result["evidence"]) == 1


# ---------------------------------------------------------------------------
# Test 2: No findings + PASSED tests → APPROVE
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_integration_no_findings_tests_pass():
    """
    No AI findings + PASSED tests → APPROVE.
    """

    empty = _agent_result([], agent="stub")

    with (
        patch("app.orchestrator.nodes.security_agent", _mock_agent(empty)),
        patch("app.orchestrator.nodes.quality_agent",  _mock_agent(empty)),
        patch("app.orchestrator.nodes.test_agent",     _mock_agent(empty)),
        patch("app.orchestrator.nodes.docs_agent",     _mock_agent(empty)),
    ):
        graph = build_review_graph()

        result = await graph.ainvoke({
            "installation_id": 1,
            "owner": "test",
            "repo": "demo",
            "pr_number": 2,
            "commit_sha": "abc124",
            "diff": "# minor comment",
            "files": [{"filename": "utils.py"}],
            "test_results": [{"status": "PASSED"}],
        })

    _assert_required_keys(result)
    assert result["decision"] == "APPROVE"
    assert result["findings"] == []


# ---------------------------------------------------------------------------
# Test 3: Tests FAILED → HUMAN_REVIEW regardless of findings
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_integration_tests_fail_escalates():
    """
    Tests FAILED → always HUMAN_REVIEW, even with no AI findings.
    """

    empty = _agent_result([], agent="stub")

    with (
        patch("app.orchestrator.nodes.security_agent", _mock_agent(empty)),
        patch("app.orchestrator.nodes.quality_agent",  _mock_agent(empty)),
        patch("app.orchestrator.nodes.test_agent",     _mock_agent(empty)),
        patch("app.orchestrator.nodes.docs_agent",     _mock_agent(empty)),
    ):
        graph = build_review_graph()

        result = await graph.ainvoke({
            "installation_id": 1,
            "owner": "test",
            "repo": "demo",
            "pr_number": 3,
            "commit_sha": "abc125",
            "diff": "x = 1/0",
            "files": [{"filename": "bad.py"}],
            "test_results": [{"status": "FAILED", "tests_failed": 2, "failure_summary": ["FAILED test_bad.py::test_x"]}],
        })

    _assert_required_keys(result)
    assert result["decision"] == "HUMAN_REVIEW"


# ---------------------------------------------------------------------------
# Test 4: No test_results in state (NOT_RUN) + no findings → APPROVE
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_integration_no_tests_no_findings():
    """
    No test results + no findings → APPROVE (nothing to block on).
    """

    empty = _agent_result([], agent="stub")

    with (
        patch("app.orchestrator.nodes.security_agent", _mock_agent(empty)),
        patch("app.orchestrator.nodes.quality_agent",  _mock_agent(empty)),
        patch("app.orchestrator.nodes.test_agent",     _mock_agent(empty)),
        patch("app.orchestrator.nodes.docs_agent",     _mock_agent(empty)),
    ):
        graph = build_review_graph()

        result = await graph.ainvoke({
            "installation_id": 1,
            "owner": "test",
            "repo": "demo",
            "pr_number": 4,
            "commit_sha": "abc126",
            "diff": "# comment only",
            "files": [],
            "test_results": [{"status": "NOT_RUN"}],
        })

    _assert_required_keys(result)
    assert result["decision"] == "APPROVE"


# ---------------------------------------------------------------------------
# Test 5: Invalid finding (file not in PR) → stripped by validator
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_integration_invalid_file_reference_stripped():
    """
    AI references a file not in the PR diff — validator strips the finding.
    Validation error is recorded.
    """

    bad_finding = _make_finding(file="not_in_pr.py")
    security_result = _agent_result([bad_finding], agent="security")
    empty = _agent_result([], agent="stub")

    with (
        patch("app.orchestrator.nodes.security_agent", _mock_agent(security_result)),
        patch("app.orchestrator.nodes.quality_agent",  _mock_agent(empty)),
        patch("app.orchestrator.nodes.test_agent",     _mock_agent(empty)),
        patch("app.orchestrator.nodes.docs_agent",     _mock_agent(empty)),
    ):
        graph = build_review_graph()

        result = await graph.ainvoke({
            "installation_id": 1,
            "owner": "test",
            "repo": "demo",
            "pr_number": 5,
            "commit_sha": "abc127",
            "diff": "x = 1",
            "files": [{"filename": "main.py"}],   # NOT not_in_pr.py
            "test_results": [{"status": "PASSED"}],
        })

    _assert_required_keys(result)
    # Finding referencing non-PR file is stripped.
    assert result["findings"] == []
    # Validation error is recorded.
    assert len(result["validation_errors"]) >= 1
    # Decision is HUMAN_REVIEW because of validation errors.
    assert result["decision"] == "HUMAN_REVIEW"


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _assert_required_keys(result: dict) -> None:
    """Every graph result must contain these five keys."""
    for key in ("findings", "decision", "validation_errors", "test_results", "evidence"):
        assert key in result, f"Missing required key: {key!r}"
