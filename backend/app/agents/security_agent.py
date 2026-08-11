# pyrefly: ignore [missing-import]
from app.agents.contracts import AgentResult
from app.agents.base_agent import BaseAgent



class SecurityAgent(BaseAgent):

    name = "security"

    def build_prompt(
        self,
        diff: str,
        files: list[dict],
    ) -> str:

        return f"""
You are a senior application security code reviewer.

Analyze ONLY the code changes provided below.

Look for:

- authentication vulnerabilities
- authorization problems
- injection vulnerabilities
- SQL injection
- command injection
- XSS
- insecure deserialization
- hardcoded secrets
- credential leakage
- unsafe file handling
- path traversal
- SSRF
- insecure cryptography
- dangerous use of eval/exec
- security-sensitive configuration mistakes

Do NOT report:
- style issues
- performance issues
- vague possibilities
- issues unrelated to the changed code

Only report a finding when there is a concrete security concern.

For every finding:
- use the actual filename when possible
- use the actual changed line when possible
- explain why it is dangerous
- provide a practical fix

Return ONLY structured JSON matching the required schema.

DIFF:
{diff}

FILES:
{files}
"""