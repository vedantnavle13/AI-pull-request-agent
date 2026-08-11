"""
Phase 10 & Phase 12 — Upgraded & Hardened TestRunner.

Detects the test framework present in a checked-out repository,
runs tests via subprocess in a sanitized environment (stripping all backend
secrets and enforcing timeouts), and returns a fully-populated Pydantic TestResult.
"""

import os
import shutil
import subprocess
import time

from app.config import TEST_TIMEOUT_SECONDS
from app.models.test_results import TestResult
from app.services.test_parser import parse_pytest_output
from app.utils.logger import get_logger

logger = get_logger(__name__)


# Sensitive environment variable keys to strip from PR subprocess execution
_SECRET_ENV_KEYS = {
    "GEMINI_API_KEY",
    "GITHUB_WEBHOOK_SECRET",
    "GITHUB_PRIVATE_KEY_PATH",
    "LANGSMITH_API_KEY",
    "LANGCHAIN_API_KEY",
    "DATABASE_URL",
    "REDIS_URL",
    "GITHUB_TOKEN",
    "PRIVATE_KEY_PATH",
}


def _get_sanitized_env() -> dict[str, str]:
    """
    Build a stripped environment dict for untrusted PR code execution.
    Prevents untrusted PR code (e.g. pytest tests) from reading host/backend secrets.
    """
    clean_env = {
        k: v for k, v in os.environ.items()
        if k not in _SECRET_ENV_KEYS
        and not k.startswith("GITHUB_")
        and not k.startswith("GEMINI_")
        and not k.startswith("LANG")
    }
    clean_env["PATH"] = os.environ.get("PATH", "/usr/bin:/bin")
    clean_env["PYTHONPATH"] = "."
    return clean_env


# ---------------------------------------------------------------------------
# Framework detection
# ---------------------------------------------------------------------------

_PYTEST_MARKERS = (
    "pyproject.toml",
    "pytest.ini",
    "setup.cfg",
    "tox.ini",
)


def detect_framework(repo_path: str) -> str | None:
    """
    Return "pytest", "unittest", or None if nothing is detected.
    """
    for marker in _PYTEST_MARKERS:
        full = os.path.join(repo_path, marker)
        if os.path.isfile(full):
            try:
                content = open(full).read()
                if "pytest" in content or "[tool:pytest]" in content or "[pytest]" in content:
                    return "pytest"
            except OSError:
                pass

    for req_file in ("requirements.txt", "requirements-dev.txt", "requirements_dev.txt"):
        full = os.path.join(repo_path, req_file)
        if os.path.isfile(full):
            try:
                content = open(full).read().lower()
                if "pytest" in content:
                    return "pytest"
                if "unittest" in content:
                    return "unittest"
            except OSError:
                pass

    if os.path.isdir(os.path.join(repo_path, "tests")):
        return "pytest"

    try:
        entries = os.listdir(repo_path)
        if any(e.startswith("test_") and e.endswith(".py") for e in entries):
            return "pytest"
    except OSError:
        pass

    return None


# ---------------------------------------------------------------------------
# TestRunner
# ---------------------------------------------------------------------------

class TestRunner:
    """
    Runs a test suite against a checked-out repository with strict process isolation.

    Security rules:
    - Never uses shell=True.
    - Commands are always a list[str] from a controlled allow-list.
    - Strips all backend secrets from process environment.
    - Enforces execution timeouts (TEST_TIMEOUT_SECONDS).
    """

    def __init__(self, timeout: int = TEST_TIMEOUT_SECONDS):
        self.timeout = timeout

    def run_python_tests(self, repo_path: str) -> TestResult:
        """
        Detect the framework and run tests in `repo_path`.
        Returns a TestResult regardless of outcome (never raises).
        """
        if not os.path.isdir(repo_path):
            return TestResult(
                status="ERROR",
                stderr="Repository path does not exist.",
            )

        framework = detect_framework(repo_path)

        if framework == "pytest":
            return self._run_pytest(repo_path)

        if framework == "unittest":
            return self._run_unittest(repo_path)

        pytest_bin = shutil.which("pytest")
        if pytest_bin:
            return self._run_pytest(repo_path)

        return TestResult(
            status="NOT_RUN",
            stderr="No supported test framework detected.",
        )

    def _run_pytest(self, repo_path: str) -> TestResult:
        pytest_bin = shutil.which("pytest")
        if not pytest_bin:
            return TestResult(
                status="ERROR",
                stderr="pytest executable not found.",
                framework="pytest",
            )

        command = [pytest_bin, "-v", "--tb=short", "-q"]
        return self._execute(
            command=command,
            cwd=repo_path,
            framework="pytest",
        )

    def _run_unittest(self, repo_path: str) -> TestResult:
        import sys
        command = [sys.executable, "-m", "unittest", "discover", "-q"]
        return self._execute(
            command=command,
            cwd=repo_path,
            framework="unittest",
        )

    def _execute(
        self,
        command: list[str],
        cwd: str,
        framework: str,
    ) -> TestResult:

        command_str = " ".join(command)
        start = time.perf_counter()
        clean_env = _get_sanitized_env()

        try:
            process = subprocess.run(
                command,
                cwd=cwd,
                env=clean_env,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                # SECURITY: shell=False is the default; never pass shell=True.
            )

            duration = round(time.perf_counter() - start, 3)
            raw_stdout = process.stdout[-10_000:]
            raw_stderr = process.stderr[-10_000:]

            parsed = parse_pytest_output(
                stdout=raw_stdout,
                stderr=raw_stderr,
                exit_code=process.returncode,
                duration_seconds=duration,
            )

            return TestResult(
                status=parsed.status,
                framework=framework,
                command=command_str,
                exit_code=process.returncode,
                stdout=raw_stdout,
                stderr=raw_stderr,
                duration_seconds=duration,
                tests_total=parsed.tests_total,
                tests_passed=parsed.tests_passed,
                tests_failed=parsed.tests_failed,
                tests_skipped=parsed.tests_skipped,
                failure_summary=parsed.failure_summary,
            )

        except subprocess.TimeoutExpired as exc:
            duration = round(time.perf_counter() - start, 3)
            logger.warning("[TestRunner] Test execution TIMEOUT after %.1fs", duration)
            return TestResult(
                status="TIMEOUT",
                framework=framework,
                command=command_str,
                stdout=str(exc.stdout or "")[-10_000:],
                stderr=str(exc.stderr or "")[-10_000:],
                duration_seconds=duration,
            )


        except Exception as exc:
            duration = round(time.perf_counter() - start, 3)
            return TestResult(
                status="ERROR",
                framework=framework,
                command=command_str,
                stderr=str(exc),
                duration_seconds=duration,
            )