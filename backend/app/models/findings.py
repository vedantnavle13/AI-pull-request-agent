from pydantic import BaseModel
from typing import List


class Finding(BaseModel):
    severity: str
    category: str
    file: str
    line: int | None = None
    title: str
    description: str
    suggestion: str


class ReviewResult(BaseModel):
    findings: List[Finding]