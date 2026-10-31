"""Remove secrets from text before it is written to a cassette."""

from __future__ import annotations

import re

REDACTED = "[REDACTED]"

_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\bsk-[A-Za-z0-9_\-]{16,}"),
    re.compile(r"\b(?:ghp|gho|ghs|ghu|github_pat)_[A-Za-z0-9_]{20,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bxox[abprs]-[A-Za-z0-9\-]{10,}"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=\-]{12,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S),
]
_ASSIGNMENT = re.compile(
    r"""(?ix)
    (?P<name>[\w.\-]*(?:api[_\-]?key|token|secret|passw(?:or)?d)[\w.\-]*)
    (?P<sep>["']?\s*[:=]\s*["']?)
    (?P<value>[^\s"',;]{8,})
    """
)


def scrub_text(text: str) -> str:
    for pattern in _PATTERNS:
        text = pattern.sub(REDACTED, text)
    return _ASSIGNMENT.sub(lambda m: f"{m['name']}{m['sep']}{REDACTED}", text)
