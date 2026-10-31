"""Loop and progress detection on the container output (ADR 0006).

The runner prints machine-readable lines (see runners/aider/test-wrapper):
  [cobble:test-run N]   a local test iteration started
  [cobble:test-fail F]  it failed, with failure fingerprint F
  [cobble:test-pass]    it passed
A run is a loop when the same normalised line repeats `threshold` times in a row, or when two
consecutive test iterations fail with the same fingerprint.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07]*\x07")
_NUM = re.compile(r"\d+")
_HEX = re.compile(r"\b0x[0-9a-f]+\b|\b[0-9a-f]{8,}\b")
_SPACE = re.compile(r"\s+")
_ALNUM = re.compile(r"[A-Za-z0-9]")
_MARK_RUN = re.compile(r"^\[cobble:test-run (\d+)\]$")
_MARK_FAIL = re.compile(r"^\[cobble:test-fail ([0-9a-f]{4,64})\]$")
_MARK_PASS = "[cobble:test-pass]"  # noqa: S105


def normalize(line: str) -> str:
    """Strip volatile parts (colours, numbers, hashes) so repeated lines compare equal."""
    line = _ANSI.sub("", line)
    line = _HEX.sub("H", line)
    line = _NUM.sub("N", line)
    return _SPACE.sub(" ", line).strip()


@dataclass
class Signal:
    """What a chunk of output changed."""

    iterations: int
    loop: str | None = None  # None | "repeated_line" | "same_failure"


class LoopDetector:
    def __init__(self, threshold: int = 8) -> None:
        self.threshold = max(2, threshold)
        self.iterations = 0
        self.loop: str | None = None
        self._buffer = ""
        self._last = ""
        self._repeat = 0
        self._last_fail: str | None = None

    def feed(self, data: bytes) -> Signal:
        text = self._buffer + data.decode("utf-8", errors="replace")
        parts = re.split(r"\r\n|\n|\r", text)
        self._buffer = parts.pop()
        if len(self._buffer) > 65536:  # a never-ending line: treat it as a line
            parts.append(self._buffer[:65536])
            self._buffer = ""
        for part in parts:
            self._line(part)
        return Signal(self.iterations, self.loop)

    def _line(self, raw: str) -> None:
        stripped = _ANSI.sub("", raw).strip()
        if m := _MARK_RUN.match(stripped):
            self.iterations = max(self.iterations, int(m.group(1)))
            return
        if m := _MARK_FAIL.match(stripped):
            if self._last_fail == m.group(1) and not self.loop:
                self.loop = "same_failure"
            self._last_fail = m.group(1)
            return
        if stripped == _MARK_PASS:
            self._last_fail = None
            return
        if stripped.startswith("[cobble:"):
            return
        norm = normalize(stripped)
        if not _ALNUM.search(norm):  # blank lines, separators, progress dots
            return
        if norm == self._last:
            self._repeat += 1
            if self._repeat >= self.threshold and not self.loop:
                self.loop = "repeated_line"
        else:
            self._last, self._repeat = norm, 1
