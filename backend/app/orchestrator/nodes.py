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
# 8. VALIDATE TEST RESULTS
# ============================================================

def validate_tests(state: ReviewState) -> dict:
    """
    Second validation layer.

    At this stage actual test execution has not yet
    been implemented.

    This node records the current status so that the
    workflow has a dedicated test-validation stage.
    """

    validation_errors = state.get(
        "validation_errors",
        [],
    )

    if validation_errors:
        return {
            "test_results": [
                {
                    "status": "BLOCKED",
                    "message": (
                        "Test validation blocked because "
                        "AI finding validation failed."
                    ),
                }
            ]
        }

    return {
        "test_results": [
            {
                "status": "NOT_RUN",
                "message": (
                    "Actual test execution will be "
                    "implemented in the next phase."
                ),
            }
        ]
    }


# ============================================================
# 9. FINAL DECISION
# ============================================================

def final_decision(state: ReviewState) -> dict:
    """
    Decide whether the PR can be automatically approved
    or requires human review.
    """

    findings = state.get("findings", [])

    validation_errors = state.get(
        "validation_errors",
        [],
    )

    # Never auto-approve invalid AI output.
    if validation_errors:
        return {
            "decision": "HUMAN_REVIEW"
        }

    # HIGH / CRITICAL findings require human review.
    high_severity = {
        "HIGH",
        "CRITICAL",
    }

    requires_review = any(
        finding.get("severity") in high_severity
        for finding in findings
    )

    if requires_review:
        return {
            "decision": "HUMAN_REVIEW"
        }

    return {
        "decision": "APPROVE"
    }