import requests


class GitHubClient:

    def __init__(self, token: str):
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
        }

    def get_pull_request_files(
        self,
        owner: str,
        repo: str,
        pr_number: int
    ):
        url = (
            f"https://api.github.com/repos/"
            f"{owner}/{repo}/pulls/{pr_number}/files"
        )

        response = requests.get(
            url,
            headers=self.headers
        )

        response.raise_for_status()

        return response.json()