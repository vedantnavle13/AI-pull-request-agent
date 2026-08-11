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

    # -------------------------
    # Specialist agent results
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
    # Test validation
    # -------------------------

    test_results: list[dict[str, Any]]

    # -------------------------
    # Final decision
    # -------------------------

    decision: str