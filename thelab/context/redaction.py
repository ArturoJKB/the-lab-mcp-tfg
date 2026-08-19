"""Defensive secret redaction for context indexing.

This module applies best-effort pattern-based redaction to text before it
enters the searchable SQLite index. It is not a cryptographic guarantee;
 callers must still avoid logging raw secrets.
"""

from __future__ import annotations

import re

# Replacement marker used for all redacted secret-like content.
_REDACTED = "[REDACTED]"


# Ordered list of (name, compiled regex, replacement) tuples.
# More specific/longer patterns should appear before shorter ones.
_PATTERNS: list[tuple[str, re.Pattern[str], str]] = [
    (
        "private_key_block",
        re.compile(
            r"-----BEGIN ([A-Z ]+ )?PRIVATE KEY-----[^-]+-----END ([A-Z ]+ )?PRIVATE KEY-----",
            re.IGNORECASE | re.DOTALL,
        ),
        _REDACTED,
    ),
    (
        "bearer_token",
        re.compile(r"\b[Bb]earer\s+[A-Za-z0-9_\-\.]+"),
        "Bearer [REDACTED]",
    ),
    (
        "github_pat_token",
        re.compile(r"\bgithub_pat_[A-Za-z0-9_]+"),
        _REDACTED,
    ),
    (
        "github_oauth_token",
        re.compile(r"\bgho_[A-Za-z0-9_]+"),
        _REDACTED,
    ),
    (
        "github_classic_token",
        re.compile(r"\bghp_[A-Za-z0-9_]+"),
        _REDACTED,
    ),
    (
        "google_api_key",
        re.compile(r"\bAIza[A-Za-z0-9_\-]+"),
        _REDACTED,
    ),
    (
        "aws_access_key",
        re.compile(r"\bAKIA[A-Z0-9]{16}\b"),
        _REDACTED,
    ),
    (
        "slack_token",
        re.compile(r"\bxox[bpas]-[A-Za-z0-9\-]+"),
        _REDACTED,
    ),
    (
        "api_key_sk",
        re.compile(r"\bsk-[a-zA-Z0-9]{8,}"),
        _REDACTED,
    ),
    (
        "api_key_hex",
        re.compile(r"\b(?:api[_-]?key|access[_-]?token)\s*[:=]\s*['\"]?[A-Za-z0-9_\-\.]{16,}['\"]?"),
        _REDACTED,
    ),
    (
        "password_assignment",
        re.compile(r"\b(?:password|passwd|pwd)\s*[:=]\s*['\"]?[^\s'\"]+['\"]?"),
        _REDACTED,
    ),
    (
        "env_secret",
        re.compile(r"\b(?:SECRET|API_KEY|TOKEN|PASSWORD|PRIVATE_KEY)\s*[:=]\s*['\"]?[^\s'\"]+['\"]?"),
        _REDACTED,
    ),
]


def redact(text: str) -> str:
    """Return a redacted copy of *text* with secret-like patterns masked.

    If *text* is empty or contains no matches, it is returned unchanged.
    """
    result = text
    for _name, pattern, replacement in _PATTERNS:
        result = pattern.sub(replacement, result)
    return result


def redact_dict(data: dict) -> dict:
    """Return a shallow copy of *data* with string values redacted.

    Only top-level string values are processed. Nested structures are left
    untouched to keep the function predictable and avoid over-redaction.
    """
    return {key: redact(value) if isinstance(value, str) else value for key, value in data.items()}
