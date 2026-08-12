import time
import requests
from app.utils.logger import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Structured GitHub Exceptions
# ---------------------------------------------------------------------------

class GitHubAPIError(Exception):
    def __init__(self, status_code: int, message: str, response: requests.Response | None = None):
        super().__init__(f"GitHub API Error {status_code}: {message}")
        self.status_code = status_code
        self.message = message
        self.response = response


class GitHubRateLimitError(GitHubAPIError):
    def __init__(self, status_code: int, message: str, retry_after: int = 60, response: requests.Response | None = None):
        super().__init__(status_code, message, response)
        self.retry_after = retry_after


class GitHubUnauthorizedError(GitHubAPIError):
    pass


class GitHubValidationError(GitHubAPIError):
    pass


class GitHubServerError(GitHubAPIError):
    pass


def _check_github_response(response: requests.Response) -> None:
    """Helper to check HTTP response and raise structured GitHub exceptions."""
    if response.status_code < 400:
        return

    status_code = response.status_code
    text = response.text

    if status_code == 429 or "rate limit" in text.lower():
        retry_after = int(response.headers.get("Retry-After", "60"))
        logger.warning("[GitHub API] Rate limit hit (429). Retry-After: %ds", retry_after)
        raise GitHubRateLimitError(status_code, text, retry_after=retry_after, response=response)

    if status_code in (401, 403):
        raise GitHubUnauthorizedError(status_code, text, response=response)

    if status_code == 422:
        raise GitHubValidationError(status_code, text, response=response)

    if status_code in (500, 502, 503, 504):
        raise GitHubServerError(status_code, text, response=response)

    raise GitHubAPIError(status_code, text, response=response)


# ---------------------------------------------------------------------------
# GitHub Client
# ---------------------------------------------------------------------------

class GitHubClient:

    def __init__(self, token: str):
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def get_pull_request_files(
        self,
        owner: str,
        repo: str,
        pr_number: int,
    ) -> list[dict]:
        url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}/files"
        response = requests.get(url, headers=self.headers, timeout=30)
        _check_github_response(response)
        return response.json()

    def create_pull_request_review(
        self,
        owner: str,
        repo: str,
        pr_number: int,
        body: str,
        event: str = "COMMENT",
    ) -> dict:
        url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}/reviews"
        payload = {"body": body, "event": event}
        response = requests.post(url, headers=self.headers, json=payload, timeout=30)
        _check_github_response(response)
        return response.json()

    def submit_pull_request_review(
        self,
        owner: str,
        repo: str,
        pr_number: int,
        commit_sha: str,
        body: str,
        event: str,
        comments: list,
    ) -> dict:
        url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}/reviews"
        payload = {
            "commit_id": commit_sha,
            "body": body,
            "event": event,
            "comments": comments,
        }
        response = requests.post(url, headers=self.headers, json=payload, timeout=30)
        _check_github_response(response)
        return response.json()

    def list_pr_reviews(
        self,
        owner: str,
        repo: str,
        pr_number: int,
        per_page: int = 100,
    ) -> list[dict]:
        url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}/reviews"
        response = requests.get(url, headers=self.headers, params={"per_page": per_page}, timeout=30)
        _check_github_response(response)
        return response.json()

    def list_pr_comments(
        self,
        owner: str,
        repo: str,
        pr_number: int,
        per_page: int = 100,
    ) -> list[dict]:
        url = f"https://api.github.com/repos/{owner}/{repo}/issues/{pr_number}/comments"
        response = requests.get(url, headers=self.headers, params={"per_page": per_page}, timeout=30)
        _check_github_response(response)
        return response.json()

    def update_comment(
        self,
        owner: str,
        repo: str,
        comment_id: int,
        body: str,
    ) -> dict:
        url = f"https://api.github.com/repos/{owner}/{repo}/issues/comments/{comment_id}"
        response = requests.patch(url, headers=self.headers, json={"body": body}, timeout=30)
        _check_github_response(response)
        return response.json()

    def create_pr_issue_comment(
        self,
        owner: str,
        repo: str,
        pr_number: int,
        body: str,
    ) -> dict:
        url = f"https://api.github.com/repos/{owner}/{repo}/issues/{pr_number}/comments"
        response = requests.post(url, headers=self.headers, json={"body": body}, timeout=30)
        _check_github_response(response)
        return response.json()

    # -----------------------------------------------------------------------
    # Phase 13 — Auto-Merge methods
    # -----------------------------------------------------------------------

    def get_pull_request(
        self,
        owner: str,
        repo: str,
        pr_number: int,
    ) -> dict:
        """
        Fetch the full PR object.
        Key fields: state, head.sha, mergeable, mergeable_state.
        """
        url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}"
        response = requests.get(url, headers=self.headers, timeout=30)
        _check_github_response(response)
        return response.json()

    def get_commit_check_runs(
        self,
        owner: str,
        repo: str,
        commit_sha: str,
    ) -> dict:
        """
        Fetch GitHub Actions / Status check-runs for a commit SHA.
        Returns the raw API response dict with `check_runs` list.
        Each check-run has: name, status, conclusion.
        """
        url = f"https://api.github.com/repos/{owner}/{repo}/commits/{commit_sha}/check-runs"
        response = requests.get(
            url,
            headers=self.headers,
            params={"per_page": 100},
            timeout=30,
        )
        _check_github_response(response)
        return response.json()

    def merge_pull_request(
        self,
        owner: str,
        repo: str,
        pr_number: int,
        expected_sha: str,
        merge_method: str = "squash",
        commit_title: str | None = None,
        commit_message: str | None = None,
    ) -> dict:
        """
        Merge a pull request with full pre-flight safety checks.

        Before calling the merge API:
          1. Re-fetch current PR to confirm it is still OPEN.
          2. Confirm current head SHA == expected_sha (HEAD_CHANGED guard).
          3. Confirm mergeable_state is not 'blocked'.

        Raises:
          GitHubAPIError(409)        if HEAD has changed.
          GitHubValidationError      if PR is not open or mergeable_state blocked.
          GitHubRateLimitError       on 429 (caller should retry).
          GitHubServerError          on 5xx (caller should retry).
        """
        # --- Pre-flight: re-fetch PR state ---
        pr = self.get_pull_request(owner=owner, repo=repo, pr_number=pr_number)

        if pr.get("state") != "open":
            raise GitHubValidationError(
                422,
                f"PR #{pr_number} is not open (state={pr.get('state')!r}). Aborting merge.",
            )

        current_sha = pr.get("head", {}).get("sha", "")
        if current_sha != expected_sha:
            raise GitHubAPIError(
                409,
                f"HEAD changed: expected {expected_sha[:8]!r} but current is {current_sha[:8]!r}.",
            )

        mergeable_state = pr.get("mergeable_state", "unknown")
        if mergeable_state == "blocked":
            raise GitHubValidationError(
                422,
                f"PR #{pr_number} mergeable_state is 'blocked'. Branch protection may prevent merge.",
            )

        # --- Perform merge ---
        url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}/merge"
        payload: dict = {
            "sha": expected_sha,
            "merge_method": merge_method,
        }
        if commit_title:
            payload["commit_title"] = commit_title
        if commit_message:
            payload["commit_message"] = commit_message

        logger.info(
            "[GitHub] Merging PR #%d (%s/%s) SHA=%s method=%s",
            pr_number, owner, repo, expected_sha[:8], merge_method,
        )
        response = requests.put(url, headers=self.headers, json=payload, timeout=30)
        _check_github_response(response)
        return response.json()