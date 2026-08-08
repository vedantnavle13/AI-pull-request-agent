from app.github.auth import get_installation_token
from app.github.client import GitHubClient
from app.github.diff import extract_diff
from app.agents.reviewer import review_code
from app.services.policy import evaluate_review






def review_pull_request(
    installation_id: int,
    owner: str,
    repo: str,
    pr_number: int,
):

    token = get_installation_token(installation_id)

    github = GitHubClient(token)

    files = github.get_pull_request_files(
        owner=owner,
        repo=repo,
        pr_number=pr_number,
    )
    print("\n========== DEBUG FILES ==========")
    print("TYPE:", type(files))
    print("VALUE:", files)
    print("=================================\n")

    changes = extract_diff(files)

    diff_text = ""

    for change in changes:

        diff_text += f"\n\nFILE: {change['filename']}\n"
        diff_text += change["patch"]

    review = review_code(diff_text)
    decision = evaluate_review(review)
    print(f"Policy decision: {decision}")
    

    review_body = format_review(review)

    github.create_pull_request_review(
        owner=owner,
        repo=repo,
        pr_number=pr_number,
        body=review_body,
    )

    submit_policy_action(
    github=github,
    owner=owner,
    repo=repo,
    pr_number=pr_number,
    review=review,
    decision=decision,
)

    return review,decision


def format_review(review):

    if not review.findings:
        return "## 🤖 AI Code Review\n\nNo significant issues found. ✅"

    output = "## 🤖 AI Code Review\n\n"

    output += f"Found **{len(review.findings)} issue(s)**.\n\n"

    for i, finding in enumerate(review.findings, start=1):

        output += f"### {i}. {finding.title}\n\n"

        output += f"**Severity:** `{finding.severity}`  \n"
        output += f"**Category:** `{finding.category}`  \n"
        output += f"**File:** `{finding.file}`  \n"

        if finding.line is not None:
            output += f"**Line:** `{finding.line}`  \n"

        output += f"\n**Problem:** {finding.description}\n\n"
        output += f"**Suggested fix:** {finding.suggestion}\n\n"

    return output    


def submit_policy_action(
    github,
    owner,
    repo,
    pr_number,
    review,
    decision,
):
    review_body = format_review(review)

    if decision == "BLOCK":

        review_body = (
            review_body
            + "\n\n❌ **AI Policy Decision: BLOCK**"
            + "\n\nHigh-severity issues must be fixed before approval."
        )

        event = "REQUEST_CHANGES"

    elif decision == "APPROVE":

        review_body = (
            review_body
            + "\n\n✅ **AI Policy Decision: APPROVE**"
        )

        event = "APPROVE"

    else:

        review_body = (
            review_body
            + "\n\n⚠️ **AI Policy Decision: HUMAN REVIEW REQUIRED**"
        )

        event = "COMMENT"

    return github.create_pull_request_review(
        owner=owner,
        repo=repo,
        pr_number=pr_number,
        body=review_body,
        event=event,
    )    

