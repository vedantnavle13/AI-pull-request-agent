from typing import Literal

from pydantic import BaseModel, Field


Severity = Literal[
    "LOW",
    "MEDIUM",
    "HIGH",
    "CRITICAL",
]


class Finding(BaseModel):
    severity: Severity
    category: str
    file: str
    line: int = Field(ge=0)

    title: str
    description: str
    suggestion: str


class AgentResult(BaseModel):
    agent: str
    findings: list[Finding]