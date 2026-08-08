import requests
import jwt
from app.github.client import GitHubClient

# pyrefly: ignore [missing-import]
from fastapi import FastAPI, Request
from app.github.auth import get_installation_token

app = FastAPI()


@app.get("/")
async def root():

    return {
        "status": "running",
        "project": "AI Pull Request Review Agent"
    }


@app.post("/webhook")
async def webhook(request: Request):

    payload = await request.json()

    if payload.get("action") != "opened":
        return {"message": "ignored"}

    repo = payload["repository"]["full_name"]

    pr_number = payload["pull_request"]["number"]

    title = payload["pull_request"]["title"]

    print(f"Repository : {repo}")
    print(f"PR Number  : {pr_number}")
    print(f"Title      : {title}")

    return {"status": "ok"}




@app.get("/token")
def token():

    installation_id = 152019445

    token = get_installation_token(installation_id)

    return {
        "token": token
    }    


@app.get("/test-pr")
async def test_pr():

    installation_id = 152019445

    token = get_installation_token(installation_id)

    github = GitHubClient(token)

    files = github.get_pull_request_files(
        owner="vedantnavle13",
        repo="AI-pull-request-agent",
        pr_number=1
    )

    return {
        "files": files
    }    