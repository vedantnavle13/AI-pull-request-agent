# System Architecture — AI Pull Request Review Agent

## Overview

The AI Pull Request Review Agent automatically reviews incoming pull requests on GitHub using a multi-agent LangGraph workflow. It validates code quality, security vulnerabilities, test coverage, and documentation impact, submitting structured summary and inline review comments directly to the GitHub PR.

```
GitHub Webhook Event
       │
       ▼
FastAPI Webhook (/webhook)
       │  (Signature & Idempotency Check)
       ▼
PostgreSQL (review_runs) + Redis Queue
       │
       ▼
ARQ Worker (review_worker.py)
       │
       ├── GitHub HEAD Checkout (PRCheckout)
       ├── Subprocess Isolated Tests (TestRunner)
       │
       ▼
LangGraph Parallel Execution
       ├── Security Agent (Gemini)
       ├── Quality Agent (Gemini)
       ├── Test Agent (Gemini)
       └── Docs Agent (Gemini)
       │
       ▼
Aggregation & Validation Subsystem
       ├── FindingValidator
       ├── EvidenceValidator
       └── Policy Engine (APPROVE / HUMAN_REVIEW / REJECT)
       │
       ▼
ReviewPublisher
       ├── Finding Hash Idempotency
       ├── Inline Review Comments (with 422 fallback)
       └── Summary PR Comment
```

## Core Components

1. **FastAPI Webhook Server (`app/main.py`)**:
   - `POST /webhook`: HMAC-SHA256 signature verification and delivery idempotency.
   - `GET /health`: Liveness probe.
   - `GET /ready`: Readiness probe verifying PostgreSQL and Redis connectivity.

2. **Database & State Machine (`app/database/`)**:
   - `review_runs`: Tracks full review lifecycle (`RECEIVED`, `QUEUED`, `PROCESSING`, `AI_REVIEWING`, `VALIDATING`, `POLICY_DECISION`, `PUBLISHING`, `COMPLETED`, `FAILED`, `DEAD_LETTER`).
   - `published_comments`: Prevents duplicate inline GitHub comments.
   - `llm_usage`: Per-agent Gemini token counts and cost estimation.
   - `review_metrics`: Duration breakdowns per pipeline stage.

3. **Multi-Agent Orchestrator (`app/orchestrator/`)**:
   - Built on LangGraph state graph.
   - Executes 4 specialist agents in parallel (`SecurityAgent`, `QualityAgent`, `TestAgent`, `DocsAgent`).
   - Merges findings and validates against PR diff hunks and test execution evidence.

4. **Review Publisher (`app/github/review.py`)**:
   - Normalizes file paths and checks line bounds.
   - Posts inline comments for eligible findings.
   - Handles 422 validation errors with safe summary fallback.
