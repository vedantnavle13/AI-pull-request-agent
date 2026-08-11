# Security Model & Untrusted Code Sandbox

## Overview

Pull Request code is inherently untrusted. The AI Pull Request Review Agent enforces strict security boundaries between the host environment/secrets and the PR code execution sandbox.

## Security Controls

### 1. Secret Environment Variable Stripping
When `TestRunner` executes tests against a checked-out PR repository:
- All sensitive environment variables (`GEMINI_API_KEY`, `GITHUB_TOKEN`, `GITHUB_WEBHOOK_SECRET`, `GITHUB_PRIVATE_KEY_PATH`, `DATABASE_URL`, `REDIS_URL`, `LANGSMITH_API_KEY`) are stripped from the process environment (`_get_sanitized_env()`).
- Untrusted test code (e.g., `os.environ.get('GEMINI_API_KEY')`) evaluates to `None`.

### 2. Secret Redaction Filter
- All log records pass through `SecretRedactingFilter` ([app/utils/logger.py](file:///Users/vedant13/AI-pull-request-agent/backend/app/utils/logger.py)).
- Automatically redacts API keys (`GEMINI_API_KEY`, `LANGSMITH_API_KEY`), GitHub App tokens (`ghp_*`, `ghs_*`), and private RSA keys (`-----BEGIN PRIVATE KEY-----`).

### 3. Subprocess Command Restrictions
- Commands are explicitly constructed lists of arguments (e.g., `['pytest', '-v']`).
- `shell=True` is **never** used.

### 4. Process Timeouts & Resource Controls
- `TEST_TIMEOUT_SECONDS=120`: If test execution hangs or attempts an infinite loop, the subprocess is killed and returns `TIMEOUT` status.
- Checkout repositories are created in isolated temporary directories (`/tmp/pr_*`) and cleaned up immediately in a `finally` block.
