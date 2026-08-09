from dotenv import load_dotenv
import os

load_dotenv()

GITHUB_APP_ID = os.getenv("GITHUB_APP_ID")
PRIVATE_KEY_PATH = os.getenv("GITHUB_PRIVATE_KEY_PATH")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GITHUB_WEBHOOK_SECRET = os.getenv(
    "GITHUB_WEBHOOK_SECRET"
)

DATABASE_URL = (
    "postgresql://localhost:5432/ai_pull_request_agent"
)