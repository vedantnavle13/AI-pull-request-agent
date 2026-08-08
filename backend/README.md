# Backend — AI Pull Request Review Agent

This directory contains the FastAPI backend for the AI Pull Request Review Agent.

## Current Flow

```text
GitHub Webhook
      |
      v
app/main.py
      |
      v
review_service.py
      |
      +--> GitHubClient
      |       |
      |       +--> authenticate
      |       +--> fetch PR files
      |
      +--> reviewer.py
      |       |
      |       +--> Google Gemini
      |       +--> ReviewResult
      |
      +--> policy.py
      |
      v
GitHub PR Review
```

## Important Modules

### `app/main.py`

FastAPI application and GitHub webhook endpoint.

```text
POST /webhook
```

Responsibilities:

- Receive webhook
- Validate webhook signature
- Read GitHub event information
- Start the PR review workflow
- Return the webhook response

### `app/github/auth.py`

Handles GitHub App authentication and installation tokens.

### `app/github/client.py`

Wrapper around the GitHub API.

Current responsibilities:

- Fetch PR changed files
- Create PR reviews
- Support review events such as `COMMENT` and `APPROVE`

### `app/github/diff.py`

Converts GitHub's changed-file response into the internal diff representation used by the reviewer.

### `app/github/validator.py`

Validates GitHub's HMAC-SHA256 webhook signature.

### `app/agents/reviewer.py`

Calls Google Gemini and converts the model output into the structured `ReviewResult` schema.

### `app/models/findings.py`

Defines the Pydantic contract:

```text
Finding
ReviewResult
```

### `app/services/policy.py`

Converts review findings into:

```text
BLOCK
HUMAN_REVIEW
APPROVE
```

### `app/services/review_service.py`

Coordinates:

```text
GitHub -> Diff -> Gemini -> Policy -> GitHub Review
```

### `app/services/idempotency.py`

Current in-memory webhook delivery ID tracking.

This is temporary and will later be replaced with persistent database-backed idempotency.

## Run

From this directory:

```bash
source ../venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

## Test Gemini Directly

```bash
python -m app.agents.test_gemini
```

## Environment

Create:

```text
.env
```

with values similar to:

```env
GEMINI_API_KEY=...
GITHUB_APP_ID=...
GITHUB_WEBHOOK_SECRET=...
```

Never commit `.env` or the GitHub App private key.

## Current Development Status

Working:

- GitHub App webhook
- GitHub App authentication
- PR file retrieval
- Gemini review
- Structured findings
- Policy decisions
- GitHub PR comments/reviews
- AI approval path
- Webhook signature validation
- Basic delivery-ID idempotency

Next:

- Filter `pull_request` actions
- PR + HEAD SHA idempotency
- PostgreSQL persistence
- Redis + ARQ worker
- LangGraph multi-agent orchestration
- Inline review comments
