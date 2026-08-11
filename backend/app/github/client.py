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