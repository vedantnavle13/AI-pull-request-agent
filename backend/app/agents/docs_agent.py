from app.agents.base_agent import BaseAgent


class DocsAgent(BaseAgent):

    name = "docs"

    def build_prompt(
        self,
        diff: str,
        files: list[dict],
    ) -> str:

        return f"""
You are a senior software engineer reviewing documentation quality.

Analyze ONLY the pull-request changes.

Look for documentation problems such as:

- changed public APIs without documentation
- changed behaviour that requires documentation
- missing docstrings for important public functions
- outdated documentation caused by the change
- misleading comments
- TODOs that create important ambiguity

Do NOT report documentation issues for trivial internal changes.

Only report meaningful documentation gaps.

For every finding:
- identify the relevant file
- explain what documentation is missing or incorrect
- suggest what should be documented

Return ONLY structured JSON matching the required schema.

DIFF:
{diff}

FILES:
{files}
"""