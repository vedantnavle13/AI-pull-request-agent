from typing import Literal

from pydantic import BaseModel


EvidenceType = Literal[
    "TEST_RESULT",
    "STATIC_ANALYSIS",
    "DIFF",
    "FILE",
    "UNKNOWN",
]


class Evidence(BaseModel):
    """
    A single piece of evidence that can support or contradict an AI finding.

    Evidence is created by the EvidenceValidator and stored in LangGraph
    state so the final policy node can make informed decisions.
    """

    type: EvidenceType

    # Human-readable description of what this evidence shows.
    description: str

    # Where the evidence came from (e.g. "pytest", "diff", "file:main.py").
    source: str | None = None

    # True  → this evidence supports the associated finding.
    # False → the finding is unsubstantiated or contradicted by evidence.
    supports_finding: bool = False
