from app.agents.base_agent import BaseAgent


class TestAgent(BaseAgent):

    name = "test"

    def build_prompt(
        self,
        diff: str,
        files: list[dict],
    ) -> str:

        return f"""
You are a senior software engineer specializing in testing.

Analyze the pull-request changes.

Determine whether the changed behaviour is adequately tested.

Look for:

- missing tests
- missing edge-case tests
- incorrect existing tests
- tests that do not actually validate the new behaviour
- missing error-condition tests
- missing boundary-condition tests
- regression risks

Do NOT automatically report a problem just because no test file
was changed. Consider the nature of the change.

For each meaningful testing gap:
- identify the relevant file
- explain what behaviour is untested
- suggest a concrete test case

Return ONLY structured JSON matching the required schema.

DIFF:
{diff}

FILES:
{files}
"""