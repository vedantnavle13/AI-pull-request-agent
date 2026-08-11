"""
Phase 10.8 — Unit tests for PRCheckout.

All subprocess calls are mocked — no real git operations.
Verifies token masking in error messages.
"""

import os
import subprocess
import tempfile
from unittest.mock import patch, MagicMock

from app.services.repo_checkout import PRCheckout, _mask_token


# ---------------------------------------------------------------------------
# _mask_token helper
# ---------------------------------------------------------------------------

def test_mask_token_replaces_token():
    url = "https://x-access-token:ghs_abc123@github.com/owner/repo.git"
    masked = _mask_token(url)
    assert "ghs_abc123" not in masked
    assert "<REDACTED>" in masked


def test_mask_token_leaves_safe_text_unchanged():
    safe = "some error message without a token"
    assert _mask_token(safe) == safe


# ---------------------------------------------------------------------------
# Successful checkout
# ---------------------------------------------------------------------------

def test_checkout_success():
    checkout = PRCheckout(timeout=30)

    fake_proc = MagicMock()
    fake_proc.returncode = 0
    fake_proc.stdout = ""
    fake_proc.stderr = ""

    with patch("subprocess.run", return_value=fake_proc):
        result = checkout.checkout(
            owner="owner",
            repo="repo",
            pr_number=42,
            token="fake-token",
        )

    assert result.success is True
    assert result.path is not None
    assert result.error is None

    # Clean up the tempdir created during checkout.
    if result.path and os.path.exists(result.path):
        import shutil
        shutil.rmtree(result.path, ignore_errors=True)


# ---------------------------------------------------------------------------
# Clone failure — token must NOT appear in error message
# ---------------------------------------------------------------------------

def test_checkout_clone_failure_masks_token():
    checkout = PRCheckout(timeout=30)

    real_token = "ghs_supersecret_token_xyz"

    err = subprocess.CalledProcessError(
        returncode=128,
        cmd=["git", "clone", f"https://x-access-token:{real_token}@github.com/o/r.git", "/tmp/x"],
        stderr=f"fatal: repo not found https://x-access-token:{real_token}@github.com/o/r.git",
    )

    with patch("subprocess.run", side_effect=err):
        result = checkout.checkout(
            owner="owner",
            repo="repo",
            pr_number=1,
            token=real_token,
        )

    assert result.success is False
    # Token must be masked in the error string.
    assert real_token not in (result.error or "")
    assert "<REDACTED>" in (result.error or "")


# ---------------------------------------------------------------------------
# Fetch failure
# ---------------------------------------------------------------------------

def test_checkout_fetch_failure():
    checkout = PRCheckout(timeout=30)

    call_count = 0

    def _side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # Clone succeeds.
            proc = MagicMock()
            proc.returncode = 0
            proc.stdout = ""
            proc.stderr = ""
            return proc
        # Fetch fails.
        raise subprocess.CalledProcessError(
            returncode=1,
            cmd=["git", "fetch", "origin", "pull/1/head"],
            stderr="fatal: couldn't find remote ref",
        )

    with patch("subprocess.run", side_effect=_side_effect):
        result = checkout.checkout(
            owner="owner",
            repo="repo",
            pr_number=1,
            token="fake-token",
        )

    assert result.success is False
    assert result.path is None


# ---------------------------------------------------------------------------
# cleanup() removes the directory
# ---------------------------------------------------------------------------

def test_cleanup_removes_directory():
    checkout = PRCheckout()

    with tempfile.TemporaryDirectory() as d:
        # Create a file inside so it's non-empty.
        with open(os.path.join(d, "dummy.txt"), "w") as f:
            f.write("x")

        checkout.cleanup(d)
        assert not os.path.exists(d)


def test_cleanup_none_is_safe():
    checkout = PRCheckout()
    # Should not raise.
    checkout.cleanup(None)


def test_cleanup_nonexistent_path_is_safe():
    checkout = PRCheckout()
    checkout.cleanup("/nonexistent/path/that/should/not/exist")
