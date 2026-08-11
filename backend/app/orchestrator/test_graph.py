from app.orchestrator.graph import build_review_graph


def test_review_graph():

    graph = build_review_graph()

    result = graph.invoke({
        "installation_id": 1,
        "owner": "test",
        "repo": "demo",
        "pr_number": 1,
        "commit_sha": "abc123",
        "diff": "print('hello')",
        "files": [],
    })

    assert "findings" in result
    assert "decision" in result
    assert "validation_errors" in result