"""
Phase 11 — Tests for ReviewPublisher.

All GitHub API calls are mocked.
Zero Gemini calls. Zero network calls. Zero DB calls.
"""

from unittest.mock import MagicMock, patch, call

import pytest

from app.github.review import ReviewPublisher, _build_summary_body, _build_inline_comment_obj


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

COMMIT_SHA = "abc123def456"


def _make_finding(
    file: str = "addition.py",
    line: int = 10,
    title: str = "ZeroDivisionError",
    severity: str = "HIGH",
    category: str = "bug",
    description: str = "Division by zero.",
    suggestion: str = "Check denominator.",
) -> dict:
    return dict(
        file=file, line=line, title=title,
        severity=severity, category=category,
        description=description, suggestion=suggestion,
    )


def _make_github(*, comment_bodies: list[str] | None = None, review_bodies: list[str] | None = None):
    """
    Return a mock GitHubClient.
    comment_bodies controls what list_pr_comments returns.
    review_bodies controls what list_pr_reviews returns.
    """
    github = MagicMock()
    github.submit_pull_request_review.return_value = {"id": 99}
    github.list_pr_comments.return_value = [
        {"body": body, "id": i + 1}
        for i, body in enumerate(comment_bodies or [])
    ]
    github.list_pr_reviews.return_value = [
        {"body": body, "id": i + 100}
        for i, body in enumerate(review_bodies or [])
    ]
    return github


def _files_with_line_10():
    """PR file list where addition.py has line 10 in the diff."""
    patch_str = "@@ -8,5 +8,5 @@\n context\n context\n+new line\n context\n context"
    return [{"filename": "addition.py", "patch": patch_str}]


def _files_without_line_10():
    """PR file list where addition.py does NOT have line 10 in the diff."""
    patch_str = "@@ -1,3 +1,3 @@\n context\n+new line\n context"
    return [{"filename": "addition.py", "patch": patch_str}]


# ---------------------------------------------------------------------------
# Test 4: Finding on a changed line → inline comment
# ---------------------------------------------------------------------------

def test_inline_finding_in_diff():
    """Line 10 is in the diff → one inline comment is sent."""

    github = _make_github()
    finding = _make_finding(file="addition.py", line=10)

    # Manufacture a patch where line 10 is in the diff.
    patch_str = (
        "@@ -8,5 +8,5 @@\n"
        " context\n"           # line 8
        " context\n"           # line 9
        "+changed line\n"      # line 10  ← ADDED
        " context\n"           # line 11
        " context\n"           # line 12
    )
    files = [{"filename": "addition.py", "patch": patch_str}]

    publisher = ReviewPublisher()
    
    with patch("app.github.review.is_comment_published", return_value=False), \
         patch("app.github.review.record_published_comment"):
         
        result = publisher.publish(
            github=github,
            owner="owner", repo="repo",
            pr_number=1, commit_sha=COMMIT_SHA,
            findings=[finding],
            files=files,
            decision="HUMAN_REVIEW",
            test_results=[],
            validation_errors=[],
        )

    assert result["inline_count"] == 1
    assert result["summary_only_count"] == 0

    # submit_pull_request_review must be called with 1 inline comment.
    call_kwargs = github.submit_pull_request_review.call_args.kwargs
    assert len(call_kwargs["comments"]) == 1
    assert call_kwargs["comments"][0]["line"] == 10
    assert call_kwargs["comments"][0]["path"] == "addition.py"
    assert call_kwargs["comments"][0]["side"] == "RIGHT"


# ---------------------------------------------------------------------------
# Test 5: Finding outside diff → summary only, no pipeline failure
# ---------------------------------------------------------------------------

def test_finding_outside_diff():
    """Line 100 is NOT in the diff → zero inline comments, no exception."""

    github = _make_github()
    finding = _make_finding(file="addition.py", line=100)
    files = _files_without_line_10()

    publisher = ReviewPublisher()
    result = publisher.publish(
        github=github,
        owner="owner", repo="repo",
        pr_number=1, commit_sha=COMMIT_SHA,
        findings=[finding],
        files=files,
        decision="HUMAN_REVIEW",
        test_results=[],
        validation_errors=[],
    )

    assert result["inline_count"] == 0
    assert result["summary_only_count"] == 1

    # Must still post the review (summary), just without inline comments.
    call_kwargs = github.submit_pull_request_review.call_args.kwargs
    assert call_kwargs["comments"] == []
    assert "ZeroDivisionError" in call_kwargs["body"]


# ---------------------------------------------------------------------------
# Test 6: Two findings in same PR → one GitHub review call
# ---------------------------------------------------------------------------

def test_two_findings_one_review_call():
    """Two findings that are in the diff → one submit_pull_request_review call."""

    github = _make_github()

    patch_str = (
        "@@ -1,5 +1,5 @@\n"
        "+line 1\n"
        "+line 2\n"
        "+line 3\n"
        "+line 4\n"
        "+line 5\n"
    )
    files = [{"filename": "addition.py", "patch": patch_str}]

    findings = [
        _make_finding(file="addition.py", line=2, title="Issue A"),
        _make_finding(file="addition.py", line=4, title="Issue B"),
    ]

    publisher = ReviewPublisher()
    
    with patch("app.github.review.is_comment_published", return_value=False), \
         patch("app.github.review.record_published_comment"):
        publisher.publish(
            github=github,
            owner="owner", repo="repo",
            pr_number=1, commit_sha=COMMIT_SHA,
            findings=findings,
            files=files,
            decision="HUMAN_REVIEW",
            test_results=[],
            validation_errors=[],
        )

    # Must be exactly ONE call to the review API.
    assert github.submit_pull_request_review.call_count == 1

    comments = github.submit_pull_request_review.call_args.kwargs["comments"]
    assert len(comments) == 2


# ---------------------------------------------------------------------------
# Test: Inline failure → graceful fallback, summary still posted
# ---------------------------------------------------------------------------

def test_inline_failure_graceful_fallback():
    """
    If submit_pull_request_review fails on first call (inline),
    it must retry without inline comments and the summary is posted.
    """

    github = _make_github()

    # First call (with inline) raises; second call (summary only) succeeds.
    github.submit_pull_request_review.side_effect = [
        Exception("GitHub rejected inline comment: invalid line"),
        {"id": 42},
    ]

    patch_str = "@@ -1,3 +1,4 @@\n+line 1\n+line 2\n+line 3\n+line 4\n"
    files = [{"filename": "addition.py", "patch": patch_str}]
    finding = _make_finding(file="addition.py", line=2)

    publisher = ReviewPublisher()
    
    with patch("app.github.review.is_comment_published", return_value=False), \
         patch("app.github.review.record_published_comment"):
         
        result = publisher.publish(
            github=github,
            owner="owner", repo="repo",
            pr_number=1, commit_sha=COMMIT_SHA,
            findings=[finding],
            files=files,
            decision="HUMAN_REVIEW",
            test_results=[],
            validation_errors=[],
        )

    # Must have retried.
    assert github.submit_pull_request_review.call_count == 2
    # Fallback call must have empty comments.
    second_call_kwargs = github.submit_pull_request_review.call_args.kwargs
    assert second_call_kwargs["comments"] == []
    # Result id comes from the fallback call.
    assert result["github_review_id"] == 42


# ---------------------------------------------------------------------------
# Test: Duplicate summary detection
# ---------------------------------------------------------------------------

def test_summary_not_reposted_for_same_commit():
    """
    If our marker is already in an existing PR comment, the summary body
    must be empty string on the review call (not re-posted).
    """

    existing_marker = f"<!-- ai-pr-agent:{COMMIT_SHA} -->"
    github = _make_github(comment_bodies=[existing_marker + "\n## 🤖 AI Code Review\n..."])

    publisher = ReviewPublisher()
    publisher.publish(
        github=github,
        owner="owner", repo="repo",
        pr_number=1, commit_sha=COMMIT_SHA,
        findings=[],
        files=[],
        decision="APPROVE",
        test_results=[],
        validation_errors=[],
    )

    # The review API should not be called at all if summary already exists and no inline comments exist.
    assert github.submit_pull_request_review.call_count == 0



def test_summary_reposted_for_different_commit():
    """
    A comment exists but for a DIFFERENT commit SHA — summary must be posted.
    """

    existing_marker = "<!-- ai-pr-agent:DIFFERENT_SHA -->"
    github = _make_github(comment_bodies=[existing_marker + "\n## 🤖 AI Code Review\n..."])

    publisher = ReviewPublisher()
    publisher.publish(
        github=github,
        owner="owner", repo="repo",
        pr_number=1, commit_sha=COMMIT_SHA,
        findings=[],
        files=[],
        decision="APPROVE",
        test_results=[],
        validation_errors=[],
    )

    call_kwargs = github.submit_pull_request_review.call_args.kwargs
    # Body must NOT be empty — this is a new commit.
    assert COMMIT_SHA in call_kwargs["body"]


# ---------------------------------------------------------------------------
# Test 1+2: Same delivery / same commit → 1 review (idempotency via claim_review)
# These are logic tests at the main.py / repository level, not publisher level.
# We verify the claim_review uniqueness key is (repo, pr_number, commit_sha).
# ---------------------------------------------------------------------------

def test_claim_review_key_includes_commit_sha():
    """
    Verify that same PR + new commit SHA is treated as a different review.
    This is a contract test — the key used must include commit_sha.
    """
    from app.database.repository import claim_review

    # We're not testing DB here — just checking the function signature
    # accepts the three uniqueness dimensions.
    import inspect
    sig = inspect.signature(claim_review)
    params = list(sig.parameters.keys())
    assert "repository" in params
    assert "pr_number" in params
    assert "commit_sha" in params


# ---------------------------------------------------------------------------
# _build_summary_body contains the commit marker
# ---------------------------------------------------------------------------

def test_summary_body_contains_commit_marker():
    body = _build_summary_body(
        findings=[],
        summary_only_findings=[],
        decision="APPROVE",
        test_results=[],
        validation_errors=[],
        commit_sha="mysha123",
    )
    assert "<!-- ai-pr-agent:mysha123 -->" in body


# ---------------------------------------------------------------------------
# _build_inline_comment — line in diff / not in diff
# ---------------------------------------------------------------------------

def test_build_inline_comment_obj():
    finding = _make_finding(file="foo.py", line=5)
    comment = _build_inline_comment_obj(finding, "foo.py", 5)
    assert comment is not None
    assert comment["line"] == 5
    assert comment["path"] == "foo.py"
    assert comment["side"] == "RIGHT"



def test_inline_finding_with_leading_dot_slash_and_string_line():
    """
    Finding file is './addition.py' and line is string '10' -> must match diff for 'addition.py' line 10.
    """
    github = _make_github()
    finding = _make_finding(file="./addition.py", line="10")

    patch_str = (
        "@@ -8,5 +8,5 @@\n"
        " context\n"
        " context\n"
        "+changed line\n"      # line 10
        " context\n"
        " context\n"
    )
    files = [{"filename": "addition.py", "patch": patch_str}]

    publisher = ReviewPublisher()

    with patch("app.github.review.is_comment_published", return_value=False), \
         patch("app.github.review.record_published_comment"):

        result = publisher.publish(
            github=github,
            owner="owner", repo="repo",
            pr_number=1, commit_sha=COMMIT_SHA,
            findings=[finding],
            files=files,
            decision="HUMAN_REVIEW",
            test_results=[],
            validation_errors=[],
        )

    assert result["inline_count"] == 1
    call_kwargs = github.submit_pull_request_review.call_args.kwargs
    assert call_kwargs["comments"][0]["path"] == "addition.py"
    assert call_kwargs["comments"][0]["line"] == 10

