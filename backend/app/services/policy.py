from app.models.findings import ReviewResult


BLOCKING_SEVERITIES = {
    "CRITICAL",
    "HIGH",
}


def evaluate_review(review: ReviewResult) -> str:

    for finding in review.findings:

        if finding.severity.upper() in BLOCKING_SEVERITIES:
            return "BLOCK"

    if review.findings:
        return "HUMAN_REVIEW"

    return "APPROVE"