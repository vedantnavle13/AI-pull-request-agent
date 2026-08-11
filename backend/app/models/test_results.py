from typing import Literal

from pydantic import BaseModel, Field


class TestResult(BaseModel):
    """
    Structured result of running a test suite against a PR checkout.

    JSON-serializable and safe to pass through LangGraph state or
    store in PostgreSQL.
    """

    status: Literal[
        "PASSED",
        "FAILED",
        "ERROR",
        "TIMEOUT",
        "NOT_RUN",
    ]

    # Which test framework was detected / used.
    framework: str | None = None

    # The exact command that was executed.
    command: str | None = None

    # Process exit code (None when timeout / error prevented completion).
    exit_code: int | None = None

    # Raw output (truncated to avoid huge state payloads).
    stdout: str = ""
    stderr: str = ""

    # Wall-clock duration of the test run.
    duration_seconds: float = 0.0

    # Parsed test counts (None = parser could not determine the value).
    tests_total: int | None = None
    tests_passed: int | None = None
    tests_failed: int | None = None
    tests_skipped: int | None = None

    # One line per failing test, e.g. "FAILED test_foo.py::test_bar".
    failure_summary: list[str] = Field(default_factory=list)