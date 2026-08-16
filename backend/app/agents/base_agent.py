import os
import time
import logging

from google import genai
from google.genai import types
from google.genai.errors import APIError
from pydantic import ValidationError
from dotenv import load_dotenv

load_dotenv()

# Ensure LangSmith env vars are loaded before langsmith is imported.
import app.config  # noqa: F401  — side-effect: sets LANGCHAIN_* env vars

from langsmith import traceable
from app.agents.contracts import AgentResult
from app.utils.logger import get_logger

logger = get_logger(__name__)


class BaseAgent:

    name: str = "base"

    def __init__(self):
        api_key = os.getenv("GEMINI_API_KEY")

        if not api_key:
            raise RuntimeError("GEMINI_API_KEY is not set")

        self.client = genai.Client(api_key=api_key)

        self.model = os.getenv("GEMINI_MODEL", "gemini-3.7-flash")
        self.last_usage: dict = {}

    def review(
        self,
        diff: str,
        files: list[dict],
    ) -> AgentResult:
        """
        Run this agent's Gemini review call.
        Wrapped with @traceable so every Gemini call appears as a
        separate span in LangSmith under the parent run.
        """
        return self._traced_review(diff=diff, files=files)

    @traceable(
        run_type="llm",
    )
    def _traced_review(
        self,
        diff: str,
        files: list[dict],
    ) -> AgentResult:
        """
        The actual Gemini call — wrapped by @traceable.
        Includes automatic retry for 429 RESOURCE_EXHAUSTED rate limit errors
        and Pydantic validation error handling for structured JSON outputs.
        """

        prompt = self.build_prompt(
            diff=diff,
            files=files,
        )

        logger.debug("[%s] Calling Gemini model=%s", self.name, self.model)

        max_retries = int(os.getenv("GEMINI_MAX_RETRIES", "5"))

        response = None
        for attempt in range(1, max_retries + 1):
            try:
                response = self.client.models.generate_content(
                    model=self.model,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        temperature=0.1,
                        response_mime_type="application/json",
                        response_schema=AgentResult,
                    ),
                )
                break
            except APIError as e:
                err_str = str(e)
                is_rate_limit   = "429" in err_str or "RESOURCE_EXHAUSTED" in err_str
                is_server_error = "503" in err_str or "UNAVAILABLE" in err_str or "500" in err_str

                if (is_rate_limit or is_server_error) and attempt < max_retries:
                    # 503 = server overload → wait longer; 429 = rate limit → shorter wait
                    base = 10.0 if is_server_error else 2.0
                    wait_time = base * (2 ** (attempt - 1))  # exponential backoff
                    wait_time = min(wait_time, 60.0)         # cap at 60 s
                    reason = "503 Unavailable (high demand)" if is_server_error else "429 Rate Limit"
                    logger.warning(
                        "[%s] Gemini %s — retrying in %.0fs (attempt %d/%d)",
                        self.name, reason, wait_time, attempt, max_retries,
                    )
                    time.sleep(wait_time)
                else:
                    raise
            except Exception as e:
                err_str = str(e)
                is_rate_limit   = "429" in err_str or "RESOURCE_EXHAUSTED" in err_str
                is_server_error = "503" in err_str or "UNAVAILABLE" in err_str or "500" in err_str

                if (is_rate_limit or is_server_error) and attempt < max_retries:
                    base = 10.0 if is_server_error else 2.0
                    wait_time = min(base * (2 ** (attempt - 1)), 60.0)
                    reason = "503 Unavailable" if is_server_error else "Rate Limit"
                    logger.warning(
                        "[%s] Gemini %s (%s) — retrying in %.0fs (attempt %d/%d)",
                        self.name, reason, type(e).__name__, wait_time, attempt, max_retries,
                    )
                    time.sleep(wait_time)
                else:
                    raise

        if not response or not response.text:
            raise RuntimeError(f"INVALID_AI_RESPONSE: {self.name} agent returned empty response")

        # Parse & Validate structured JSON
        try:
            result = AgentResult.model_validate_json(response.text)
        except (ValidationError, Exception) as exc:
            logger.error("[%s] INVALID_AI_RESPONSE: Failed to parse output: %s", self.name, exc)
            raise ValueError(f"INVALID_AI_RESPONSE: {exc}") from exc

        # Extract token usage metadata if available
        usage_meta = getattr(response, "usage_metadata", None)
        if usage_meta:
            input_tokens = getattr(usage_meta, "prompt_token_count", None)
            output_tokens = getattr(usage_meta, "candidates_token_count", None)
            total_tokens = getattr(usage_meta, "total_token_count", None)
        else:
            input_tokens = output_tokens = total_tokens = None

        self.last_usage = {
            "agent": self.name,
            "model": self.model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total_tokens,
        }

        logger.info(
            "[%s] Gemini returned %d finding(s) (tokens: input=%s, output=%s, total=%s)",
            self.name,
            len(result.findings),
            input_tokens,
            output_tokens,
            total_tokens,
        )

        return result

    def build_prompt(
        self,
        diff: str,
        files: list[dict],
    ) -> str:

        raise NotImplementedError