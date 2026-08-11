def build_review_comments(findings: list) -> list:
    comments = []

    for finding in findings:

        if not finding.get("file"):
            continue

        if not finding.get("line"):
            continue

        comments.append(
            {
                "path": finding["file"],
                "line": finding["line"],
                "side": "RIGHT",
                "body": (
                    f"### {finding['title']}\n\n"
                    f"**Severity:** {finding['severity']}\n\n"
                    f"{finding['description']}\n\n"
                    f"**Suggestion:** {finding['suggestion']}"
                ),
            }
        )

    return comments