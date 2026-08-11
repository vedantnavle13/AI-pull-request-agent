from unittest.mock import patch, MagicMock

from app.agents.contracts import AgentResult, Finding
from app.orchestrator.graph import build_review_graph


# ---------------------------------------------------------------------------
# Fake data – no Gemini API calls are made during this test
# ---------------------------------------------------------------------------

FAKE_SECURITY_RESULT = AgentResult(
    agent="security",
    findings=[
        Finding(
            title="Hardcoded secret",
            description="A secret is hardcoded in the diff.",
            severity="HIGH",
            category="security",
            file="main.py",
            line=1,
            suggestion="Use environment variables instead.",
        )
    ],
)

EMPTY_RESULT = AgentResult(agent="stub", findings=[])


def _mock_agent(result: AgentResult) -> MagicMock:
    agent = MagicMock()
    agent.review.return_value = result
    return agent


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_review_graph():
    """
    Verify the graph wiring end-to-end WITHOUT hitting the Gemini API.

    All four specialist agents are patched so the test is fast,
    deterministic, and costs zero API quota.
    """

    mock_security = _mock_agent(FAKE_SECURITY_RESULT)
    mock_quality  = _mock_agent(EMPTY_RESULT)
    mock_tests    = _mock_agent(EMPTY_RESULT)
    mock_docs     = _mock_agent(EMPTY_RESULT)

    with (
        patch("app.orchestrator.nodes.security_agent", mock_security),
        patch("app.orchestrator.nodes.quality_agent",  mock_quality),
        patch("app.orchestrator.nodes.test_agent",     mock_tests),
        patch("app.orchestrator.nodes.docs_agent",     mock_docs),
    ):
        graph = build_review_graph()

        result = graph.invoke({
            "installation_id": 1,
            "owner": "test",
            "repo": "demo",
            "pr_number": 1,
            "commit_sha": "abc123",
            "diff": "print('hello')",
            "files": [{"filename": "main.py"}],
            # Pre-populate test_results as the worker does before invoke().
            "test_results": [{"status": "PASSED"}],
        })

    # Required keys must always be present.
    assert "findings" in result
    assert "decision" in result
    assert "validation_errors" in result
    assert "evidence" in result

    # HIGH severity finding → graph must escalate to human review.
    assert result["decision"] == "HUMAN_REVIEW"

    # Each agent called exactly once.
    mock_security.review.assert_called_once()
    mock_quality.review.assert_called_once()
    mock_tests.review.assert_called_once()
    mock_docs.review.assert_called_once()