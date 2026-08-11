from app.agents.base_agent import BaseAgent


class QualityAgent(BaseAgent):

    name = "quality"

    def build_prompt(
        self,
        diff: str,
        files: list[dict],
    ) -> str:

        return f"""
You are a senior software engineer performing a code-quality review.

Analyze ONLY the changed code.

Look for concrete problems involving:

- incorrect logic
- duplicated logic
- bad error handling
- resource leaks
- unreachable code
- unsafe assumptions
- poor maintainability
- unnecessary complexity
- incorrect API usage
- race-condition risks
- broken edge cases
- obvious runtime errors

Do NOT complain about:
- formatting
- personal coding style
- harmless naming preferences
- code that is merely different from your preferred style

Only report meaningful issues that could affect correctness,
maintainability, reliability, or production behaviour.

Return ONLY structured JSON matching the required schema.

DIFF:
{diff}

FILES:
{files}
"""