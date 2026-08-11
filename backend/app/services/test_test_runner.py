"""
Phase 10.3 — Unit tests for TestRunner.

All subprocess calls are mocked — no real processes are started.
No Gemini calls.
"""

import os
import tempfile
from unittest.mock import patch, MagicMock

import pytest

from app.services.test_runner import TestRunner, detect_framework


# ---------------------------------------------------------------------------
# detect_framework tests (real filesystem, temp dirs)
# ---------------------------------------------------------------------------

def test_detect_pytest_from_ini():
    with tempfile.TemporaryDirectory() as d:
        with open(os.path.join(d, "pytest.ini"), "w") as f:
            f.write("[pytest]\n")
        assert detect_framework(d) == "pytest"


def test_detect_pytest_from_pyproject():
    with tempfile.TemporaryDirectory() as d:
        with open(os.path.join(d, "pyproject.toml"), "w") as f:
            f.write("[tool.pytest.ini_options]\n")
        assert detect_framework(d) == "pytest"


def test_detect_pytest_from_requirements():
    with tempfile.TemporaryDirectory() as d:
        with open(os.path.join(d, "requirements.txt"), "w") as f:
            f.write("pytest==7.4.0\n")
        assert detect_framework(d) == "pytest"


def test_detect_pytest_from_tests_dir():
    with tempfile.TemporaryDirectory() as d:
        os.makedirs(os.path.join(d, "tests"))
        assert detect_framework(d) == "pytest"


def test_detect_no_framework():
    with tempfile.TemporaryDirectory() as d:
        assert detect_framework(d) is None


# ---------------------------------------------------------------------------
# TestRunner.run_python_tests — mock subprocess
# ---------------------------------------------------------------------------

def _fake_process(returncode: int, stdout: str = "", stderr: str = ""):
    proc = MagicMock()
    proc.returncode = returncode
    proc.stdout = stdout
    proc.stderr = stderr
    return proc


def test_runner_passed():
    runner = TestRunner(timeout=30)
    stdout = "========================= 2 passed in 0.30s =========================\n"

    with tempfile.TemporaryDirectory() as d:
        # Create a tests/ dir so framework = "pytest" is detected.
        os.makedirs(os.path.join(d, "tests"))

        with patch("subprocess.run", return_value=_fake_process(0, stdout)):
            result = runner.run_python_tests(d)

    assert result.status == "PASSED"
    assert result.framework == "pytest"
    assert result.exit_code == 0


def test_runner_failed():
    runner = TestRunner(timeout=30)
    stdout = (
        "FAILED tests/test_x.py::test_bad\n"
        "========================= 1 failed in 0.50s =========================\n"
    )

    with tempfile.TemporaryDirectory() as d:
        os.makedirs(os.path.join(d, "tests"))

        with patch("subprocess.run", return_value=_fake_process(1, stdout)):
            result = runner.run_python_tests(d)

    assert result.status == "FAILED"
    assert result.exit_code == 1
    assert len(result.failure_summary) >= 1


def test_runner_timeout():
    import subprocess

    runner = TestRunner(timeout=1)

    with tempfile.TemporaryDirectory() as d:
        os.makedirs(os.path.join(d, "tests"))

        with patch(
            "subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="pytest", timeout=1),
        ):
            result = runner.run_python_tests(d)

    assert result.status == "TIMEOUT"
    assert result.exit_code is None


def test_runner_missing_pytest():
    runner = TestRunner()

    with tempfile.TemporaryDirectory() as d:
        os.makedirs(os.path.join(d, "tests"))

        # Simulate pytest binary not found.
        with patch("shutil.which", return_value=None):
            result = runner.run_python_tests(d)

    # With no pytest found and no fallback: NOT_RUN or ERROR are both acceptable.
    assert result.status in ("ERROR", "NOT_RUN")


def test_runner_bad_path():
    runner = TestRunner()
    result = runner.run_python_tests("/nonexistent/path/that/does/not/exist")
    assert result.status == "ERROR"
    assert "does not exist" in result.stderr


def test_runner_generic_exception():
    runner = TestRunner()

    with tempfile.TemporaryDirectory() as d:
        os.makedirs(os.path.join(d, "tests"))

        with patch("subprocess.run", side_effect=OSError("disk full")):
            result = runner.run_python_tests(d)

    assert result.status == "ERROR"
    assert "disk full" in result.stderr
