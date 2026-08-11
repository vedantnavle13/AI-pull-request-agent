import os
import re
import shutil
import subprocess
import tempfile

from dataclasses import dataclass


@dataclass
class CheckoutResult:
    success: bool
    path: str | None
    error: str | None = None


# Mask anything that looks like a GitHub token in a URL.
_TOKEN_RE = re.compile(r"x-access-token:[^@]+@")


def _mask_token(text: str) -> str:
    """Replace GitHub token in a URL with a placeholder."""
    return _TOKEN_RE.sub("x-access-token:<REDACTED>@", text)


class PRCheckout:

    def __init__(self, timeout: int = 120):
        self.timeout = timeout

    def checkout(
        self,
        owner: str,
        repo: str,
        pr_number: int,
        token: str,
    ) -> CheckoutResult:

        workdir = tempfile.mkdtemp(
            prefix=f"pr_{owner}_{repo}_{pr_number}_"
        )

        repo_url = (
            f"https://x-access-token:{token}"
            f"@github.com/{owner}/{repo}.git"
        )

        try:
            self._run(
                [
                    "git",
                    "clone",
                    "--depth",
                    "1",
                    repo_url,
                    workdir,
                ],
                cwd=None,
            )

            self._run(
                [
                    "git",
                    "fetch",
                    "origin",
                    f"pull/{pr_number}/head",
                ],
                cwd=workdir,
            )

            self._run(
                [
                    "git",
                    "checkout",
                    "FETCH_HEAD",
                ],
                cwd=workdir,
            )

            return CheckoutResult(
                success=True,
                path=workdir,
            )

        except subprocess.CalledProcessError as exc:
            shutil.rmtree(workdir, ignore_errors=True)

            # SECURITY: never leak the GitHub token in error messages.
            safe_stderr = _mask_token(exc.stderr or "")
            safe_cmd    = _mask_token(" ".join(str(a) for a in exc.cmd))

            return CheckoutResult(
                success=False,
                path=None,
                error=f"git command failed: {safe_cmd!r}\n{safe_stderr}",
            )

        except Exception as exc:
            shutil.rmtree(workdir, ignore_errors=True)
            return CheckoutResult(
                success=False,
                path=None,
                error=_mask_token(str(exc)),
            )

    def cleanup(self, path: str | None) -> None:

        if path and os.path.exists(path):
            shutil.rmtree(path, ignore_errors=True)

    def _run(
        self,
        command: list[str],
        cwd: str | None,
    ):

        return subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=self.timeout,
            check=True,
        )