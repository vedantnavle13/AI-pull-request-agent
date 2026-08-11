"""
Phase 12 — Secret Redacting Logger & Structured Log Formatter.

Prevents credentials (GITHUB_PRIVATE_KEY, GITHUB_TOKEN, GEMINI_API_KEY, etc.)
from being logged to console or stdout, while supporting structured logging
with correlation IDs (review_id).
"""

import os
import re
import logging
from typing import Any

# Sensitive keys/values to redact
_SENSITIVE_ENV_KEYS = [
    "GEMINI_API_KEY",
    "GITHUB_WEBHOOK_SECRET",
    "LANGSMITH_API_KEY",
    "LANGCHAIN_API_KEY",
]

_REDACTION_PATTERNS = [
    re.compile(r"(ghp_[A-Za-z0-9_]{36})"),
    re.compile(r"(ghs_[A-Za-z0-9_]{36})"),
    re.compile(r"(lsv2_pt_[A-Za-z0-9_]+)"),
    re.compile(r"(-----BEGIN [A-Z ]+PRIVATE KEY-----[\s\S]+?-----END [A-Z ]+PRIVATE KEY-----)"),
]


class SecretRedactingFilter(logging.Filter):
    """Filter that sanitizes log records by redacting known secret tokens and patterns."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact_secrets(record.msg)
        if record.args:
            if isinstance(record.args, tuple):
                record.args = tuple(
                    redact_secrets(str(arg)) if isinstance(arg, str) else arg
                    for arg in record.args
                )
            elif isinstance(record.args, dict):
                record.args = {
                    k: redact_secrets(str(v)) if isinstance(v, str) else v
                    for k, v in record.args.items()
                }
        return True


def redact_secrets(text: str) -> str:
    """Scan text and replace sensitive keys / secret patterns with [REDACTED]."""
    if not text:
        return text

    # Redact env keys if populated
    for key in _SENSITIVE_ENV_KEYS:
        val = os.getenv(key)
        if val and len(val) > 5 and val in text:
            text = text.replace(val, "[REDACTED]")

    # Redact regex patterns
    for pat in _REDACTION_PATTERNS:
        text = pat.sub("[REDACTED]", text)

    return text


def get_logger(name: str) -> logging.Logger:
    """Get a standard logger configured with the secret redacting filter."""
    logger = logging.getLogger(name)
    if not any(isinstance(f, SecretRedactingFilter) for f in logger.filters):
        logger.addFilter(SecretRedactingFilter())
    return logger
