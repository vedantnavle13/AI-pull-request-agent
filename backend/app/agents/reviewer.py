# pyrefly: ignore [missing-import]
from langchain_google_genai import ChatGoogleGenerativeAI
from app.config import GEMINI_API_KEY
from app.models.findings import ReviewResult


model = ChatGoogleGenerativeAI(
    model="gemini-3.6-flash",
    google_api_key=GEMINI_API_KEY,
)


def review_code(diff: str):

    prompt = f"""
You are a senior software engineer reviewing a GitHub Pull Request.

Analyze ONLY the code changes provided below.

Look for:

1. Bugs
2. Security vulnerabilities
3. Performance problems
4. Serious coding problems

Do NOT report harmless style preferences.

For every real issue, provide:

- severity: CRITICAL, HIGH, MEDIUM, or LOW
- category: BUG, SECURITY, PERFORMANCE, or QUALITY
- file
- line number if identifiable
- short title
- detailed description
- suggested fix

If there are no meaningful problems, return an empty findings array.

CODE CHANGES:

{diff}
"""

    structured_model = model.with_structured_output(ReviewResult)

    result = structured_model.invoke(prompt)

    return result