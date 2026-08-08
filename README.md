# AI Pull Request Review Agent

An AI-powered GitHub Pull Request review agent that automatically analyzes PR changes using Google Gemini, produces structured findings, evaluates them with a policy engine, and posts the review back to GitHub.

> **Current status:** Working MVP  
> The current system can receive GitHub PR webhooks, fetch changed files, review the diff with Gemini, make a policy decision, and post an approval/review back to the PR.

## Current Architecture

```text
GitHub Pull Request
        |
        v
GitHub App Webhook
        |
        v
FastAPI /webhook
        |
        +--> HMAC-SHA256 signature validation
        |
        +--> Webhook delivery idempotency
        |
        v
GitHub API
        |
        v
PR changed files / patches
        |
        v
Gemini
        |
        v
Structured ReviewResult
        |
        v
Policy Engine
        |
        +--> BLOCK
        +--> HUMAN_REVIEW
        +--> APPROVE
        |
        v
GitHub Pull Request Review
```

## What Has Been Implemented

### GitHub integration

- GitHub App created and connected to the test repository.
- GitHub webhook receives Pull Request events.
- GitHub App installation authentication is implemented.
- PR changed files are fetched through the GitHub API.
- AI reviews are posted back to the GitHub PR.

### AI review

The reviewer uses **Google Gemini**, not OpenAI.

The model is prompted to look for:

- Bugs
- Security vulnerabilities
- Performance problems
- Serious code-quality problems

The reviewer returns structured Pydantic models rather than relying on free-form text.

Example finding:

```json
{
  "severity": "HIGH",
  "category": "SECURITY",
  "file": "auth.py",
  "line": 3,
  "title": "SQL Injection Vulnerability",
  "description": "User input is directly concatenated into the SQL query.",
  "suggestion": "Use parameterized queries."
}
```

### Policy engine

The current policy maps findings to:

| Decision | Condition | GitHub action |
|---|---|---|
| `BLOCK` | HIGH or CRITICAL finding | Request changes |
| `HUMAN_REVIEW` | Other findings | Comment |
| `APPROVE` | No findings | Approve |

The approval path has been tested successfully on a clean PR.

## Project Structure

```text
AI-pull-request-agent/
├── backend/
│   ├── app/
│   │   ├── agents/
│   │   │   ├── reviewer.py
│   │   │   └── test_gemini.py
│   │   ├── api/
│   │   ├── database/
│   │   ├── github/
│   │   │   ├── auth.py
│   │   │   ├── client.py
│   │   │   ├── diff.py
│   │   │   └── validator.py
│   │   ├── models/
│   │   │   └── findings.py
│   │   ├── services/
│   │   │   ├── idempotency.py
│   │   │   ├── policy.py
│   │   │   └── review_service.py
│   │   ├── config.py
│   │   └── main.py
│   ├── .env
│   ├── private-key.pem
│   └── requirements.txt
├── frontend/
├── docker-compose.yml
├── .gitignore
└── README.md
```

## Local Setup

### 1. Clone the repository

```bash
git clone <your-repository-url>
cd AI-pull-request-agent
```

### 2. Create and activate the virtual environment

```bash
python3 -m venv venv
source venv/bin/activate
```

### 3. Install backend dependencies

```bash
cd backend
pip install -r requirements.txt
```

### 4. Configure environment variables

Create:

```text
backend/.env
```

Example:

```env
GEMINI_API_KEY=your_gemini_api_key

GITHUB_APP_ID=your_github_app_id
GITHUB_WEBHOOK_SECRET=your_webhook_secret
```

Your GitHub App private key should remain local and must never be committed.

## Run the Backend

From the `backend` directory:

```bash
uvicorn app.main:app --reload
```

The API will normally be available at:

```text
http://localhost:8000
```

The webhook endpoint is:

```text
POST /webhook
```

Opening `/webhook` directly in a browser sends a GET request, so a `405 Method Not Allowed` response is expected.

## Exposing the Webhook Locally

GitHub cannot reach `localhost` directly.

Use ngrok:

```bash
ngrok http 8000
```

Then configure the GitHub App webhook URL as:

```text
https://<ngrok-domain>/webhook
```

## Security

The webhook validates GitHub's `X-Hub-Signature-256` using HMAC-SHA256 before processing the payload.

Secrets that must stay out of Git:

- Gemini API key
- GitHub webhook secret
- GitHub App private key
- Any access tokens

Make sure `.env` and `private-key.pem` are included in `.gitignore`.

## Current Limitations

This is an MVP and is intentionally not yet production-ready.

Current limitations include:

- Webhook idempotency is currently based on the GitHub delivery ID and is stored in memory.
- Multiple different GitHub events for the same PR can still result in multiple reviews.
- The review currently operates on the PR file patches rather than sophisticated line-level diff mapping.
- AI approval is based on the current policy engine and should not yet be treated as a complete production security gate.
- Processing is currently synchronous inside the webhook request.
- PostgreSQL, Redis/ARQ, LangGraph, multi-agent review, observability, and the dashboard are not yet integrated.

## Planned Roadmap

### Phase 1 — Reliability

- Filter webhook events/actions.
- Use PR number + repository + HEAD commit as review idempotency key.
- Move idempotency state to PostgreSQL.
- Move review processing to Redis + ARQ workers.

### Phase 2 — Multi-Agent Review

Introduce LangGraph with specialist agents:

```text
PR Diff
   |
   v
Orchestrator
   |
   +--> Security Agent
   +--> Quality Agent
   +--> Test Agent
   +--> Documentation Agent
   |
   v
Aggregator
   |
   v
Policy Engine
```

### Phase 3 — Better GitHub Reviews

- Inline comments on exact changed lines.
- Better diff/line mapping.
- Improved review summaries.

### Phase 4 — Observability

- Review history
- Agent execution events
- Latency tracking
- Token/cost tracking
- Audit trail

### Phase 5 — Dashboard

Build the planned Next.js dashboard for:

- PR reviews
- Findings
- Human-in-the-loop queue
- Review history
- Agent performance
- Cost and latency metrics

### Phase 6 — Automatic Merge

Only after the review and policy system is reliable:

```text
PR
 |
 +--> Tests pass
 +--> Security checks pass
 +--> No blocking AI findings
 +--> Repository policy satisfied
 +--> Required approvals satisfied
 |
 v
Automatic merge
```

## Development Philosophy

The project is being built incrementally:

1. Make one end-to-end path work.
2. Verify it against a real GitHub PR.
3. Add reliability.
4. Add architectural complexity only when it solves a real problem.

The current working milestone is the **single-agent GitHub PR review + policy decision MVP**.
