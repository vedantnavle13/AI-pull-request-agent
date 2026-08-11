# Reliability & Resilience — AI Pull Request Review Agent

## Hardening Mechanisms (Phase 12)

### 1. Unique Review Identity & Idempotency
Reviews are keyed by:
```
(installation_id, owner, repo, pr_number, commit_sha)
```
- **Same commit SHA twice**: Duplicate webhook or worker execution skips without re-processing.
- **New commit SHA**: Created as a distinct new review run.

### 2. Stale Worker Recovery
If a worker crashes while in state `PROCESSING`, `AI_REVIEWING`, `VALIDATING`, `POLICY_DECISION`, or `PUBLISHING` for longer than `REVIEW_STALE_TIMEOUT_SECONDS` (default 900s / 15 mins):
- The next webhook or claim reclaims the review run.
- Increments `attempt_count` and retries execution.

### 3. Bounded Exponential Backoff Retries
- **Transient Failures**: Retried automatically (HTTP 429, 500, 502, 503, 504, network timeouts, connection resets).
- **Non-Retryable Failures**: Failed immediately without retrying (HTTP 400, 401, 403, 422, malformed JSON).
- **Dead Letter Handling**: If `attempt_count >= MAX_REVIEW_RETRIES` (3), the review run transitions to `DEAD_LETTER` with `error_type` and `error_message`.

### 4. GitHub API 422 Inline Fallback
If GitHub rejects inline review comment payloads (e.g. outdated diff line):
- Logs structured error: `[INLINE_REVIEW_FAILED] status=422 filename=... line=...`
- Automatically falls back to summary-only review comment.

### 5. Gemini API 422 / 429 Rate-Limit Protection
- `BaseAgent` retries 429 rate limit responses with exponential backoff (2s, 4s, 8s).
- Validates model output using Pydantic (`AgentResult`). Raises `ValueError("INVALID_AI_RESPONSE...")` on malformed schema.
