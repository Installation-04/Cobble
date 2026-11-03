"""Keep secrets out of logs, events and error messages (CLAUDE.md rule 8)."""

from __future__ import annotations

import logging
import threading

MIN_LENGTH = 8  # shorter values would mangle ordinary text; generated secrets are far longer
MASK = "***"


class Redactor:
    """Replaces every registered secret value found in a text."""

    def __init__(self) -> None:
        self._values: set[str] = set()
        self._lock = threading.Lock()

    def register(self, value: str) -> None:
        if len(value) >= MIN_LENGTH:
            with self._lock:
                self._values.add(value)

    def redact(self, text: str) -> str:
        with self._lock:
            values = sorted(self._values, key=len, reverse=True)  # longest first
        for value in values:
            text = text.replace(value, MASK)
        return text


class RedactingFilter(logging.Filter):
    """A logging filter that masks registered secrets in the message, arguments and traceback."""

    def __init__(self, redactor: Redactor) -> None:
        super().__init__()
        self._redactor = redactor

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = self._redactor.redact(record.getMessage())
        record.args = None
        if record.exc_info:
            formatted = logging.Formatter().formatException(record.exc_info)
            record.exc_text = self._redactor.redact(formatted)
            record.exc_info = None
        return True
