import requests


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
    ):

        url = (
            f"https://api.github.com/repos/"
            f"{owner}/{repo}/pulls/{pr_number}/files"
        )

        response = requests.get(
            url,
            headers=self.headers,
        )

        response.raise_for_status()

        data = response.json()

        print(
            "GitHub status:",
            response.status_code,
        )

        print(
            "GitHub response type:",
            type(data),
        )

        print(
            "GitHub response:",
            data,
        )

        return data

    def create_pull_request_review(
        self,
        owner: str,
        repo: str,
        pr_number: int,
        body: str,
        event: str = "COMMENT",
    ):

        url = (
            f"https://api.github.com/repos/"
            f"{owner}/{repo}/pulls/{pr_number}/reviews"
        )

        payload = {
            "body": body,
            "event": event,
        }

        response = requests.post(
            url,
            headers=self.headers,
            json=payload,
        )

        response.raise_for_status()

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
    ):

        url = (
            f"https://api.github.com/repos/"
            f"{owner}/{repo}/pulls/{pr_number}/reviews"
        )

        payload = {
            "commit_id": commit_sha,
            "body": body,
            "event": event,
            "comments": comments,
        }

        response = requests.post(
            url,
            headers=self.headers,
            json=payload,
        )

        response.raise_for_status()

        return response.json()