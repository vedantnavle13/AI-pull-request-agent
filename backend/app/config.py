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