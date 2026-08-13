from dotenv import load_dotenv
import os

load_dotenv()

GITHUB_APP_ID = os.getenv("GITHUB_APP_ID")
PRIVATE_KEY_PATH = os.getenv("GITHUB_PRIVATE_KEY_PATH")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GITHUB_WEBHOOK_SECRET = os.getenv(
    "GITHUB_WEBHOOK_SECRET"
)

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://localhost:5432/ai_pull_request_agent"
)

REDIS_HOST = os.getenv("REDIS_HOST", "127.0.0.1")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_DB = int(os.getenv("REDIS_DB", "0"))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD")
REDIS_SSL = os.getenv("REDIS_SSL", "false").lower() == "true"

# ---------------------------------------------------------------------------
# Phase 3 — Multi-user SaaS / OAuth
# ---------------------------------------------------------------------------

# GitHub App OAuth credentials (found in GitHub App settings under "OAuth App Settings").
# Required for the /auth/github/* login flow.
GITHUB_CLIENT_ID     = os.getenv("GITHUB_CLIENT_ID", "")
GITHUB_CLIENT_SECRET = os.getenv("GITHUB_CLIENT_SECRET", "")

# Secret key for signing application session JWTs.
# Generate with: openssl rand -hex 32
APP_SECRET_KEY = os.getenv("APP_SECRET_KEY", "change-me-in-production-use-openssl-rand-hex-32")

# Frontend origin used for OAuth redirect URLs.
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")

# ---------------------------------------------------------------------------
# Phase 12 — Reliability & Sandbox Configuration
# ---------------------------------------------------------------------------

MAX_REVIEW_RETRIES = int(os.getenv("MAX_REVIEW_RETRIES", "3"))
RETRY_BASE_DELAY_SECONDS = float(os.getenv("RETRY_BASE_DELAY_SECONDS", "2"))
REVIEW_STALE_TIMEOUT_SECONDS = int(os.getenv("REVIEW_STALE_TIMEOUT_SECONDS", "900"))

GEMINI_TIMEOUT_SECONDS = int(os.getenv("GEMINI_TIMEOUT_SECONDS", "60"))
GEMINI_MAX_RETRIES = int(os.getenv("GEMINI_MAX_RETRIES", "3"))

GITHUB_TIMEOUT_SECONDS = int(os.getenv("GITHUB_TIMEOUT_SECONDS", "30"))
GITHUB_MAX_RETRIES = int(os.getenv("GITHUB_MAX_RETRIES", "3"))

TEST_TIMEOUT_SECONDS = int(os.getenv("TEST_TIMEOUT_SECONDS", "120"))
MAX_TEST_MEMORY_MB = int(os.getenv("MAX_TEST_MEMORY_MB", "512"))
MAX_TEST_CPUS = int(os.getenv("MAX_TEST_CPUS", "1"))

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# ---------------------------------------------------------------------------
# LangSmith — optional observability
# The LangSmith SDK (v0.10+) reads LANGSMITH_* env vars directly.
# Set LANGSMITH_API_KEY in .env with your real key from smith.langchain.com
# ---------------------------------------------------------------------------

LANGSMITH_API_KEY  = os.getenv("LANGSMITH_API_KEY", "")
LANGSMITH_PROJECT  = os.getenv("LANGSMITH_PROJECT", "AI-pull-request-agent")
LANGSMITH_TRACING  = os.getenv("LANGSMITH_TRACING", "")
LANGSMITH_ENDPOINT = os.getenv("LANGSMITH_ENDPOINT", "https://api.smith.langchain.com")

# Strip placeholder strings so tracing only activates with a real key.
_PLACEHOLDERS = {"<your-api-key>", "your_langsmith_api_key_here", ""}
if LANGSMITH_API_KEY in _PLACEHOLDERS:
    LANGSMITH_API_KEY = ""

if LANGSMITH_API_KEY:
    os.environ["LANGSMITH_API_KEY"]  = LANGSMITH_API_KEY
    os.environ["LANGSMITH_PROJECT"]  = LANGSMITH_PROJECT
    os.environ["LANGSMITH_ENDPOINT"] = LANGSMITH_ENDPOINT
    os.environ["LANGSMITH_TRACING"]  = "true"
    os.environ["LANGCHAIN_API_KEY"]       = LANGSMITH_API_KEY
    os.environ["LANGCHAIN_PROJECT"]       = LANGSMITH_PROJECT
    os.environ["LANGCHAIN_TRACING_V2"]    = "true"
    os.environ["LANGCHAIN_ENDPOINT"]      = LANGSMITH_ENDPOINT
else:
    os.environ["LANGSMITH_TRACING"]    = "false"
    os.environ["LANGCHAIN_TRACING_V2"] = "false"

# ---------------------------------------------------------------------------
# Phase 13 — Autonomous Approval & Auto-Merge
# ---------------------------------------------------------------------------

# Master safety switch. Must be explicitly set to "true" to enable auto-merge.
# The system remains fully functional as a review-only bot when False.
AUTO_MERGE_ENABLED: bool = os.getenv("AUTO_MERGE_ENABLED", "false").lower() == "true"

# Merge strategy: squash (default) | merge | rebase
_VALID_MERGE_METHODS = {"squash", "merge", "rebase"}
_raw_merge_method = os.getenv("AUTO_MERGE_METHOD", "squash").lower()
AUTO_MERGE_METHOD: str = _raw_merge_method if _raw_merge_method in _VALID_MERGE_METHODS else "squash"

# When True, all GitHub CI check-runs must be success/skipped before merge.
AUTO_MERGE_REQUIRE_CHECKS: bool = os.getenv("AUTO_MERGE_REQUIRE_CHECKS", "true").lower() == "true"

# ---------------------------------------------------------------------------
# Phase 14 — Observability & Economics
# ---------------------------------------------------------------------------

# Data retention (documentation only for now — no automatic deletion yet).
OBSERVABILITY_RETENTION_DAYS: int = int(os.getenv("OBSERVABILITY_RETENTION_DAYS", "90"))

# Centralized LLM pricing — cost per 1 000 tokens (USD).
# Update here only; never scatter pricing across multiple files.
# Source: https://ai.google.dev/pricing (verified 2026-08)
LLM_PRICING: dict[str, dict[str, float]] = {
    # model-alias               input $/1K   output $/1K
    "gemini-flash-latest":      {"input": 0.000075, "output": 0.000300},
    "gemini-2.0-flash":         {"input": 0.000075, "output": 0.000300},
    "gemini-2.0-flash-lite":    {"input": 0.0000375,"output": 0.000150},
    "gemini-1.5-flash":         {"input": 0.000075, "output": 0.000300},
    "gemini-1.5-flash-8b":      {"input": 0.0000375,"output": 0.000150},
    "gemini-1.5-pro":           {"input": 0.00125,  "output": 0.005000},
    "gemini-2.5-pro":           {"input": 0.00125,  "output": 0.010000},
    "gemini-2.5-flash":         {"input": 0.000075, "output": 0.000300},
    "gemini-3.6-flash":         {"input": 0.000075, "output": 0.000300},
}