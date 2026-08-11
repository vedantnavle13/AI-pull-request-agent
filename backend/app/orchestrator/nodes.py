from app.orchestrator.state import ReviewState

from app.agents.security_agent import SecurityAgent
from app.agents.quality_agent import QualityAgent
from app.agents.test_agent import TestAgent
from app.agents.docs_agent import DocsAgent
from app.agents.validator import ReviewValidator


# ============================================================
# AGENTS
# ============================================================

security_agent = SecurityAgent()
quality_agent = QualityAgent()
test_agent = TestAgent()
docs_agent = DocsAgent()


# ============================================================
# 1. BUILD CONTEXT
# ============================================================

def build_context(state: ReviewState) -> dict:
    """
    Prepare the context required by all specialist agents.

    This node does not modify agent results.
    """

    return {
        "diff": state.get("diff", ""),
        "files": state.get("files", []),
    }


# ============================================================
# 2. SECURITY AGENT
# ============================================================

def run_security(state: ReviewState) -> dict:
    result = security_agent.review(
        diff=state.get("diff", ""),
        files=state.get("files", []),
    )

    return {
        "security_findings": [
            finding.model_dump()
            for finding in result.findings
        ]
    }


# ============================================================
# 3. QUALITY AGENT
# ============================================================

def run_quality(state: ReviewState) -> dict:
    result = quality_agent.review(
        diff=state.get("diff", ""),
        files=state.get("files", []),
    )

    return {
        "quality_findings": [
            finding.model_dump()
            for finding in result.findings
        ]
    }


# ============================================================
# 4. TEST AGENT
# ============================================================

def run_tests(state: ReviewState) -> dict:
    result = test_agent.review(
        diff=state.get("diff", ""),
        files=state.get("files", []),
    )

    return {
        "test_findings": [
            finding.model_dump()
            for finding in result.findings
        ]
    }


# ============================================================
# 5. DOCUMENTATION AGENT
# ============================================================

def run_docs(state: ReviewState) -> dict:
    result = docs_agent.review(
        diff=state.get("diff", ""),
        files=state.get("files", []),
    )

    return {
        "docs_findings": [
            finding.model_dump()
            for finding in result.findings
        ]
    }


# ============================================================
# 6. AGGREGATE FINDINGS
# ============================================================

def aggregate_findings(state: ReviewState) -> dict:
    """
    Merge findings from all four specialist agents.
    """

    findings = []

    findings.extend(
        state.get("security_findings", [])
    )

    findings.extend(
        state.get("quality_findings", [])
    )

    findings.extend(
        state.get("test_findings", [])
    )

    findings.extend(
        state.get("docs_findings", [])
    )

    return {
        "findings": findings
    }


# ============================================================
# 7. VALIDATE AI RESPONSE
# ============================================================

def validate_review(state: ReviewState) -> dict:
    """
    Validate the aggregated AI findings.

    Validation checks:
    - required fields exist
    - referenced files exist
    - duplicate findings are removed
    """

    validator = ReviewValidator()

    findings = state.get("findings", [])
    files = state.get("files", [])

    validated_findings = validator.validate(
        findings=findings,
        files=files,
    )

    return {
        "findings": validated_findings,
        "validation_errors": validator.errors,
    }


# ============================================================
# 8. VALIDATE AGAINST TEST EVIDENCE
# ============================================================

def validate_tests(state: ReviewState) -> dict:
    """
    Cross-check AI findings against actual test evidence.

    test_results are pre-populated in state by the worker BEFORE
    graph.invoke() is called, so this node reads (not writes) them.
    """

    from app.agents.evidence_validator import EvidenceValidator
    from app.models.test_results import TestResult

    findings = state.get("findings", [])
    diff = state.get("diff", "")

    # Deserialize test_results dicts → TestResult objects.
    raw_test_results = state.get("test_results", [])
    test_results: list[TestResult] = []
    for r in raw_test_results:
        if isinstance(r, TestResult):
            test_results.append(r)
        elif isinstance(r, dict):
            try:
                test_results.append(TestResult(**r))
            except Exception:
                pass

    ev_validator = EvidenceValidator()
    evidence_objs, ev_errors = ev_validator.validate(
        findings=findings,
        test_results=test_results,
        diff=diff,
    )

    # Merge evidence errors into the existing validation_errors list.
    existing_errors = list(state.get("validation_errors", []))
    all_errors = existing_errors + ev_errors

    return {
        "evidence": [e.model_dump() for e in evidence_objs],
        "validation_errors": all_errors,
    }


# ============================================================
# 9. FINAL EVIDENCE-AWARE DECISION
# ============================================================

def final_decision(state: ReviewState) -> dict:
    """
    Produce the final policy decision using:
        - AI findings
        - Validation errors
        - Test results
        - Evidence

    Decisions:
        APPROVE       — no valid findings, tests pass (or not applicable)
        HUMAN_REVIEW  — findings present or inconclusive test status
        REJECT        — (reserved for future policy hardening)
    """

    findings = state.get("findings", [])
    validation_errors = state.get("validation_errors", [])
    evidence = state.get("evidence", [])
    raw_test_results = state.get("test_results", [])

    # --- 1. Never auto-approve invalid AI output. ---
    if validation_errors:
        return {"decision": "HUMAN_REVIEW"}

    # --- 2. Determine overall test status. ---
    test_statuses = set()
    for r in raw_test_results:
        if isinstance(r, dict):
            test_statuses.add(r.get("status", "NOT_RUN"))
        elif hasattr(r, "status"):
            test_statuses.add(r.status)

    tests_failed = "FAILED" in test_statuses
    tests_passed = "PASSED" in test_statuses and not tests_failed
    tests_ran    = bool(test_statuses - {"NOT_RUN", "NOT_APPLICABLE"})

    # --- 3. Tests failed → always escalate. ---
    if tests_failed:
        return {"decision": "HUMAN_REVIEW"}

    # --- 4. No valid AI findings at all. ---
    if not findings:
        if tests_passed or not tests_ran:
            return {"decision": "APPROVE"}
        # Inconclusive test state with no findings → be conservative.
        return {"decision": "HUMAN_REVIEW"}

    # --- 5. Any HIGH / CRITICAL finding → human review. ---
    high_severity = {"HIGH", "CRITICAL"}
    if any(f.get("severity") in high_severity for f in findings):
        return {"decision": "HUMAN_REVIEW"}

    # --- 6. Only LOW / MEDIUM findings remain. ---
    # Check whether evidence supports them.
    supported = [e for e in evidence if e.get("supports_finding")]

    if supported or tests_passed:
        # Evidence exists and tests pass → flag for human but note it's not severe.
        return {"decision": "HUMAN_REVIEW"}

    # Findings present but no supporting evidence and tests didn't pass clearly.
    return {"decision": "HUMAN_REVIEW"}