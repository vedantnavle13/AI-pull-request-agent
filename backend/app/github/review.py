"""
Phase 11 — ReviewPublisher.

Orchestrates publishing AI PR reviews to GitHub with inline comments and summary comments.

Key Features:
  1. Hashing each finding for per-finding inline comment idempotency.
  2. Parsing patch hunks via get_changed_lines() to ensure line numbers are in the PR diff.
  3. Path normalization (_normalize_path) to prevent matching failures due to leading ./ or /.
  4. Explicit logging of AI findings, changed lines, classifications, and exact GitHub API payloads/responses.
  5. Duplicate summary check using both PR Reviews and Issue Comments for <!-- ai-pr-agent:{sha} --> marker.
  6. Graceful fallback to summary-only review if GitHub rejects inline comments.
"""

import json
import hashlib
import logging

from app.github.diff import get_changed_lines, _normalize_path
from app.database.repository import is_comment_published, record_published_comment

logger = logging.getLogger(__name__)

# Marker embedded in every summary comment so we can detect duplicates.
_SUMMARY_MARKER_PREFIX = "<!-- ai-pr-agent:"
_SUMMARY_MARKER_SUFFIX = " -->"


# ---------------------------------------------------------------------------
# Finding hash
# ---------------------------------------------------------------------------

def finding_hash(
    repository: str,
    pr_number: int,
    commit_sha: str,
    file: str,
    line: int | None,
    category: str,
    description: str,
) -> str:
    """
    Deterministic 40-char hex hash that uniquely identifies a finding
    for a given commit. Used to prevent duplicate inline comments.
    """
    norm_file = _normalize_path(file)
    raw = (
        f"{repository}:{pr_number}:{commit_sha}"
        f":{norm_file}:{line}:{category}:{description}"
    )
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Inline comment builder
# ---------------------------------------------------------------------------

def _build_inline_comment_obj(finding: dict, path: str, line: int) -> dict:
    """Build a single GitHub inline review comment dict."""
    body_parts = [f"### 🤖 {finding.get('title', 'AI Finding')}\n\n"]

    severity = finding.get("severity", "")
    category = finding.get("category", "")
    if severity or category:
        body_parts.append(
            f"**Severity:** `{severity}` · **Category:** `{category}`\n\n"
        )

    desc = finding.get("description", "")
    if desc:
        body_parts.append(f"{desc}\n\n")

    suggestion = finding.get("suggestion", "")
    if suggestion:
        body_parts.append(f"**Suggestion:** {suggestion}\n")

    return {
        "path": path,
        "line": line,
        "side": "RIGHT",
        "body": "".join(body_parts),
    }


# ---------------------------------------------------------------------------
# Summary body builder
# ---------------------------------------------------------------------------

def _build_summary_body(
    findings: list[dict],
    summary_only_findings: list[dict],
    decision: str,
    test_results: list[dict],
    validation_errors: list[str],
    commit_sha: str,
) -> str:
    """
    Build the full markdown body for the PR review summary comment.
    Includes a hidden marker for duplicate detection.
    """
    marker = f"{_SUMMARY_MARKER_PREFIX}{commit_sha}{_SUMMARY_MARKER_SUFFIX}"
    lines = [
        f"{marker}\n",
        "## 🤖 AI Code Review\n\n",
    ]

    # --- Test result summary ---
    if test_results:
        status = test_results[0].get("status", "UNKNOWN")
        icon   = "✅" if status == "PASSED" else ("❌" if status == "FAILED" else "⚠️")
        lines.append(f"### {icon} Test Results: `{status}`\n\n")

        failed_count = test_results[0].get("tests_failed") or 0
        total_count  = test_results[0].get("tests_total")
        if total_count:
            passed_count = test_results[0].get("tests_passed", 0) or 0
            lines.append(
                f"- **{passed_count} passed** / **{failed_count} failed** / {total_count} total\n"
            )

        for fail_line in (test_results[0].get("failure_summary") or [])[:10]:
            lines.append(f"  - `{fail_line}`\n")
        lines.append("\n")

    all_listed = list(findings)

    # --- AI findings overview ---
    if not all_listed:
        lines.append("### ✅ No significant issues found by AI agents.\n\n")
    else:
        total = len(all_listed)
        inline_count = total - len(summary_only_findings)
        lines.append(f"### Found **{total} issue(s)**")
        if inline_count > 0:
            lines.append(f" — {inline_count} posted as inline comment(s)")
        lines.append("\n\n")

        for i, finding in enumerate(all_listed, 1):
            lines.append(f"#### {i}. {finding.get('title', 'Unnamed')}\n")
            lines.append(
                f"- **Severity:** `{finding.get('severity', '?')}`"
                f"  **Category:** `{finding.get('category', '?')}`\n"
            )
            lines.append(
                f"- **File:** `{finding.get('file', '?')}`"
                f"  **Line:** `{finding.get('line', '?')}`\n\n"
            )
            lines.append(f"{finding.get('description', '')}\n\n")
            if finding.get("suggestion"):
                lines.append(f"**Suggestion:** {finding['suggestion']}\n\n")

    # --- Validation warnings ---
    if validation_errors:
        lines.append(f"### ⚠️ Validation warnings ({len(validation_errors)})\n\n")
        for err in validation_errors[:5]:
            lines.append(f"- {err}\n")
        lines.append("\n")

    # --- Policy decision ---
    icons = {"APPROVE": "✅", "HUMAN_REVIEW": "👀", "REJECT": "🚫"}
    icon  = icons.get(decision, "❓")
    lines.append(f"---\n**{icon} AI Policy Decision: {decision}**\n")

    return "".join(lines)


# ---------------------------------------------------------------------------
# ReviewPublisher
# ---------------------------------------------------------------------------

class ReviewPublisher:
    """
    Orchestrates the full GitHub review publishing flow for Phase 11.

    Usage:
        publisher = ReviewPublisher()
        result = publisher.publish(github, owner, repo, ...)
    """

    def publish(
        self,
        github,             # GitHubClient
        owner: str,
        repo: str,
        pr_number: int,
        commit_sha: str,
        findings: list[dict],
        files: list[dict],
        decision: str,
        test_results: list[dict],
        validation_errors: list[str],
        repository: str = "",
    ) -> dict:
        """
        Publish the AI review to GitHub.

        Returns:
            {
                "github_review_id": int | None,
                "inline_count": int,
                "summary_only_count": int,
                "skipped_duplicates": int,
            }
        """

        print(f"\n[ReviewPublisher] === START PUBLISHING REVIEW for {owner}/{repo} PR #{pr_number} (commit {commit_sha[:8]}) ===")

        # ------------------------------------------------------------------
        # 1. Build a per-file lookup of changed line numbers.
        # ------------------------------------------------------------------

        changed_lines_by_file: dict[str, set[int]] = {}
        for f in files:
            orig_filename = f.get("filename", "")
            patch = f.get("patch", "") or ""
            lines = get_changed_lines(patch)

            norm_filename = _normalize_path(orig_filename)
            changed_lines_by_file[orig_filename] = lines
            changed_lines_by_file[norm_filename] = lines

            print(f"[ReviewPublisher] File '{orig_filename}' (norm: '{norm_filename}') patch changed lines: {sorted(list(lines))}")

        # ------------------------------------------------------------------
        # 2. Separate findings into inline-eligible vs summary-only.
        # ------------------------------------------------------------------

        inline_comments: list[dict] = []
        summary_only_findings: list[dict] = []
        skipped_duplicates = 0
        published_hashes = []

        for finding in findings:
            raw_file = finding.get("file", "")
            norm_file = _normalize_path(raw_file)

            try:
                line_num = int(finding.get("line")) if finding.get("line") is not None else None
            except (ValueError, TypeError):
                line_num = None

            print(f"[ReviewPublisher] AI finding received: file='{raw_file}' (norm: '{norm_file}'), line={line_num} (raw: {finding.get('line')!r}), title='{finding.get('title')}', severity='{finding.get('severity')}'")

            changed = changed_lines_by_file.get(raw_file) or changed_lines_by_file.get(norm_file) or set()

            if line_num is not None and line_num in changed:
                reason = f"Line {line_num} is in changed lines set for file '{norm_file}'"
                print(f"[ReviewPublisher] Classification -> INLINE-ELIGIBLE. Reason: {reason}")

                # Check DB if this specific finding was already posted.
                f_hash = finding_hash(
                    repository=repository,
                    pr_number=pr_number,
                    commit_sha=commit_sha,
                    file=raw_file,
                    line=line_num,
                    category=finding.get("category", ""),
                    description=finding.get("description", ""),
                )
                if is_comment_published(f_hash):
                    print(f"[ReviewPublisher] Skipping already published inline comment (hash={f_hash})")
                    skipped_duplicates += 1
                    continue

                # Match exact filename from PR files list if available
                target_path = raw_file
                for f in files:
                    if _normalize_path(f.get("filename")) == norm_file:
                        target_path = f.get("filename")
                        break

                comment = _build_inline_comment_obj(finding, target_path, line_num)
                inline_comments.append(comment)
                published_hashes.append(f_hash)
            else:
                if line_num is None:
                    reason = "Finding line number is missing or invalid"
                elif not changed:
                    reason = f"File '{norm_file}' not found in PR changed files list or patch is empty"
                else:
                    reason = f"Line {line_num} is not in changed lines set {sorted(list(changed))} for file '{norm_file}'"
                print(f"[ReviewPublisher] Classification -> SUMMARY-ONLY. Reason: {reason}")
                summary_only_findings.append(finding)

        # ------------------------------------------------------------------
        # 3. Check for duplicate summary comment (same commit_sha).
        # ------------------------------------------------------------------

        summary_exists = self._summary_already_posted(
            github=github,
            owner=owner,
            repo=repo,
            pr_number=pr_number,
            commit_sha=commit_sha,
        )

        # ------------------------------------------------------------------
        # 4. Build summary body.
        # ------------------------------------------------------------------

        summary_body = _build_summary_body(
            findings=findings,
            summary_only_findings=summary_only_findings,
            decision=decision,
            test_results=test_results,
            validation_errors=validation_errors,
            commit_sha=commit_sha,
        )

        # ------------------------------------------------------------------
        # 5. Submit GitHub PR review.
        # ------------------------------------------------------------------

        event = "APPROVE" if decision == "APPROVE" else "COMMENT"
        github_review_id = None

        if summary_exists:
            print(f"[ReviewPublisher] Summary review already posted for commit {commit_sha[:8]} — skipping summary body re-post.")
            if inline_comments:
                github_review_id = self._post_review(
                    github=github,
                    owner=owner,
                    repo=repo,
                    pr_number=pr_number,
                    commit_sha=commit_sha,
                    body="",          # empty body since summary already exists
                    event=event,
                    inline_comments=inline_comments,
                )
        else:
            github_review_id = self._post_review(
                github=github,
                owner=owner,
                repo=repo,
                pr_number=pr_number,
                commit_sha=commit_sha,
                body=summary_body,
                event=event,
                inline_comments=inline_comments,
            )

        print(f"[ReviewPublisher] === END PUBLISHING REVIEW: id={github_review_id}, inline={len(inline_comments)}, summary_only={len(summary_only_findings)}, skipped={skipped_duplicates} ===\n")

        # ------------------------------------------------------------------
        # 6. Record successfully published inline comments in DB.
        # ------------------------------------------------------------------
        if github_review_id is not None and inline_comments:
            for f_hash in published_hashes:
                record_published_comment(
                    finding_hash=f_hash,
                    repository=repository,
                    pr_number=pr_number,
                    commit_sha=commit_sha,
                    github_id=github_review_id,
                )

        return {
            "github_review_id": github_review_id,
            "inline_count": len(inline_comments),
            "summary_only_count": len(summary_only_findings),
            "skipped_duplicates": skipped_duplicates,
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _post_review(
        self,
        github,
        owner: str,
        repo: str,
        pr_number: int,
        commit_sha: str,
        body: str,
        event: str,
        inline_comments: list[dict],
    ) -> int | None:
        """
        Attempt to post a PR review with inline comments.
        If GitHub rejects it (e.g. bad line numbers), retry without
        inline comments to ensure the summary is always delivered.
        """
        print(f"[ReviewPublisher] Submitting GitHub Review Payload:\n"
              f"  commit_id: {commit_sha}\n"
              f"  event: {event}\n"
              f"  body_len: {len(body)}\n"
              f"  inline_comments_count: {len(inline_comments)}\n"
              f"  comments_payload: {json.dumps(inline_comments, indent=2)}")

        try:
            resp = github.submit_pull_request_review(
                owner=owner,
                repo=repo,
                pr_number=pr_number,
                commit_sha=commit_sha,
                body=body,
                event=event,
                comments=inline_comments,
            )
            print(f"[ReviewPublisher] GitHub Review Creation SUCCESS! Review ID: {resp.get('id')}")
            return resp.get("id")

        except Exception as exc:
            for comment in inline_comments:
                logger.warning(
                    "[INLINE_REVIEW_FAILED] status=422 filename=%s line=%s side=%s github_message=%s",
                    comment.get("path"),
                    comment.get("line"),
                    comment.get("side"),
                    str(exc),
                )
            print(f"[ReviewPublisher] GitHub Review Creation FAILED with inline comments!\n"
                  f"  Error: {exc}")
            if hasattr(exc, "response") and exc.response is not None:
                print(f"  GitHub Response Text: {exc.response.text}")

            print("[ReviewPublisher] Retrying review creation without inline comments (summary fallback)...")
            try:
                resp = github.submit_pull_request_review(
                    owner=owner,
                    repo=repo,
                    pr_number=pr_number,
                    commit_sha=commit_sha,
                    body=body,
                    event=event,
                    comments=[],
                )
                print(f"[ReviewPublisher] Fallback Summary Review SUCCESS! Review ID: {resp.get('id')}")
                return resp.get("id")
            except Exception as exc2:
                print(f"[ReviewPublisher] Fallback Summary Review also FAILED!\n"
                      f"  Error: {exc2}")
                if hasattr(exc2, "response") and exc2.response is not None:
                    print(f"  GitHub Response Text: {exc2.response.text}")
                return None

    def _summary_already_posted(
        self,
        github,
        owner: str,
        repo: str,
        pr_number: int,
        commit_sha: str,
    ) -> bool:
        """
        Return True if a review comment containing our commit-specific
        marker has already been posted to this PR.
        Checks both PR Reviews and Issue Comments.
        """
        marker = f"{_SUMMARY_MARKER_PREFIX}{commit_sha}{_SUMMARY_MARKER_SUFFIX}"

        try:
            # 1. Check PR Reviews
            if hasattr(github, "list_pr_reviews"):
                reviews = github.list_pr_reviews(
                    owner=owner,
                    repo=repo,
                    pr_number=pr_number,
                )
                for review in reviews:
                    body = review.get("body", "") or ""
                    if marker in body:
                        print(f"[ReviewPublisher] Found existing summary in PR reviews (id={review.get('id')}) for commit {commit_sha[:8]}")
                        return True

            # 2. Check Issue Comments
            comments = github.list_pr_comments(
                owner=owner,
                repo=repo,
                pr_number=pr_number,
            )
            for comment in comments:
                body = comment.get("body", "") or ""
                if marker in body:
                    print(f"[ReviewPublisher] Found existing summary in issue comments (id={comment.get('id')}) for commit {commit_sha[:8]}")
                    return True

        except Exception as exc:
            logger.warning("Could not fetch existing PR reviews/comments: %s", exc)

        return False