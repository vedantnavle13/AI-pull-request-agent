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

    # -------------------------
    # Phase 14 — Per-agent timing + token usage
    # Each agent writes its own keys; no cross-agent write conflict.
    # Timestamps are POSIX floats (time.time()) stored in UTC.
    # -------------------------

    security_started_at: float
    security_completed_at: float
    security_duration_ms: int
    security_success: bool
    security_usage: dict[str, Any]   # {agent, model, input_tokens, output_tokens, total_tokens}

    quality_started_at: float
    quality_completed_at: float
    quality_duration_ms: int
    quality_success: bool
    quality_usage: dict[str, Any]

    tests_started_at: float
    tests_completed_at: float
    tests_duration_ms: int
    tests_success: bool
    tests_usage: dict[str, Any]

    docs_started_at: float
    docs_completed_at: float
    docs_duration_ms: int
    docs_success: bool
    docs_usage: dict[str, Any]