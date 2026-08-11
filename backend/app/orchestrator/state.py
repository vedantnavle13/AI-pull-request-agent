from typing import TypedDict, Any


class ReviewState(TypedDict, total=False):

    # -------------------------
    # PR context
    # -------------------------

    installation_id: int
    owner: str
    repo: str
    pr_number: int
    commit_sha: str

    diff: str
    files: list[dict[str, Any]]

    # DB record ID for this review (set by worker before graph runs).
    review_id: int

    # -------------------------
    # Specialist agent results
    # (each agent writes its own key — no concurrent update conflict)
    # -------------------------

    security_findings: list[dict[str, Any]]
    quality_findings: list[dict[str, Any]]
    test_findings: list[dict[str, Any]]
    docs_findings: list[dict[str, Any]]

    # -------------------------
    # Aggregated findings
    # -------------------------

    findings: list[dict[str, Any]]

    # -------------------------
    # Validation
    # -------------------------

    validation_errors: list[str]

    # -------------------------
    # Test execution results
    # (populated by worker BEFORE graph.invoke() — not inside graph)
    # -------------------------

    test_results: list[dict[str, Any]]

    # -------------------------
    # Evidence
    # (populated by evidence_validator node inside graph)
    # -------------------------

    evidence: list[dict[str, Any]]

    # -------------------------
    # Final decision
    # -------------------------

    decision: str