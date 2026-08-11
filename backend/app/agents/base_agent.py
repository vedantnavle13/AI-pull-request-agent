import os

from google import genai
from google.genai import types
from dotenv import load_dotenv

load_dotenv()

from app.agents.contracts import AgentResult


class BaseAgent:

    name: str = "base"

    def __init__(self):
        api_key = os.getenv("GEMINI_API_KEY")

        if not api_key:
            raise RuntimeError(
                "GEMINI_API_KEY is not set"
            )

        self.client = genai.Client(
            api_key=api_key
        )

        self.model = os.getenv(
            "GEMINI_MODEL",
            "gemini-2.5-flash",
        )

    def review(
        self,
        diff: str,
        files: list[dict],
    ) -> AgentResult:

        prompt = self.build_prompt(
            diff=diff,
            files=files,
        )

        response = self.client.models.generate_content(
            model=self.model,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.1,
                response_mime_type="application/json",
                response_schema=AgentResult,
            ),
        )

        if not response.text:
            raise RuntimeError(
                f"{self.name} agent returned empty response"
            )

        return AgentResult.model_validate_json(
            response.text
        )

    def build_prompt(
        self,
        diff: str,
        files: list[dict],
    ) -> str:

        raise NotImplementedError