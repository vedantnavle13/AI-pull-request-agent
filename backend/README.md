# Backend — AI Pull Request Review Agent

An enterprise-grade, production-hardened AI agent system that reviews GitHub Pull Requests using Google Gemini and LangGraph. Automatically posts inline code comments and summary reviews on GitHub.

## Architecture

```text
GitHub Webhook
      ↓
FastAPI (app/main.py)
      ↓ HMAC-SHA256 & Idempotency
PostgreSQL (review_runs) + Redis Queue
      ↓
ARQ Worker (review_worker.py)
      ↓
PR Checkout (Isolated Directory)
      ↓
Subprocess Isolated Tests (TestRunner)
      ↓
LangGraph Orchestrator
  ├── SecurityAgent (Gemini)
  ├── QualityAgent (Gemini)
  ├── TestAgent (Gemini)
  └── DocsAgent (Gemini)
      ↓
Aggregator & Validator
  ├── FindingValidator
  └── EvidenceValidator
      ↓
Policy Engine (APPROVE / HUMAN_REVIEW / REJECT)
      ↓
ReviewPublisher (Summary + Inline Review Comments)
```

For full architectural details, see [docs/architecture.md](file:///Users/vedant13/AI-pull-request-agent/backend/docs/architecture.md).

---

## Environment Configuration

Create a `.env` file in `backend/`:

```env
APP_NAME="AI Pull Request Agent"
DEBUG=True
HOST=0.0.0.0
PORT=8000
GITHUB_APP_ID=...
GITHUB_PRIVATE_KEY_PATH=private-key.pem
GEMINI_API_KEY=...
GITHUB_WEBHOOK_SECRET=...
DATABASE_URL=postgresql://localhost:5432/ai_pull_request_agent

# Reliability & Sandbox Defaults
MAX_REVIEW_RETRIES=3
RETRY_BASE_DELAY_SECONDS=2
REVIEW_STALE_TIMEOUT_SECONDS=900

GEMINI_TIMEOUT_SECONDS=60
GEMINI_MAX_RETRIES=3

GITHUB_TIMEOUT_SECONDS=30
GITHUB_MAX_RETRIES=3

TEST_TIMEOUT_SECONDS=120
MAX_TEST_MEMORY_MB=512
MAX_TEST_CPUS=1

LOG_LEVEL=INFO

# Observability (Optional)
LANGSMITH_TRACING=true
LANGSMITH_ENDPOINT=https://api.smith.langchain.com
LANGSMITH_API_KEY=...
LANGSMITH_PROJECT=AI-pull-request-agent
```

---

## Running the Services

### 1. Start PostgreSQL & Redis
```bash
brew services start postgresql@14
brew services start redis
```

### 2. Run Database Migrations
```bash
source ../venv/bin/activate
python -c "from app.database.migrations import ensure_schema; ensure_schema()"
```

### 3. Start FastAPI Server
```bash
source ../venv/bin/activate
uvicorn app.main:app --reload --port 8000
```

### 4. Start ARQ Worker
```bash
source ../venv/bin/activate
arq app.workers.review_worker.WorkerSettings
```

---

## API & Health Probes

- **Liveness Probe**: `GET /health` (`status: ok`)
- **Readiness Probe**: `GET /ready` (Verifies PostgreSQL and Redis connectivity)
- **GitHub Webhook**: `POST /webhook`
- **Review Status Query**: `GET /reviews/{owner}/{repo}/{pr_number}/{commit_sha}`

---

## Running Tests

Run the complete 104+ test suite:

```bash
source ../venv/bin/activate
pytest
```

Run Phase 12 reliability regression tests:

```bash
pytest tests/phase12/test_phase12_reliability.py -v
```

---

## Security & Reliability Documentation

- [docs/architecture.md](file:///Users/vedant13/AI-pull-request-agent/backend/docs/architecture.md)
- [docs/reliability.md](file:///Users/vedant13/AI-pull-request-agent/backend/docs/reliability.md)
- [docs/security.md](file:///Users/vedant13/AI-pull-request-agent/backend/docs/security.md)
