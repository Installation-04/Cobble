"""From a model's reply to a verdict: extract the code, wrap it with the hidden cases, read the
result back. The program built here is only ever executed by the sandbox."""

from __future__ import annotations

import json
import re
import secrets
from dataclasses import dataclass

from .tasks import Task

SYSTEM_PROMPT = (
    "You write Python. Reply with exactly one ```python code block that defines the requested "
    "function (and any helper it needs). No explanation, no example calls, no tests, no input()."
)

MARKER = "__COBBLE_BENCH__"
_FENCE = re.compile(r"```(?:python|py)?[ \t]*\n(.*?)```", re.DOTALL | re.IGNORECASE)


def task_messages(task: Task) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Write this function.\n\n{task.prompt}"},
    ]


def extract_code(reply: str) -> str | None:
    """The first fenced block, else the whole reply if it looks like code; None otherwise."""
    match = _FENCE.search(reply)
    if match:
        code = match.group(1).strip()
        return code or None
    if "def " in reply:
        return reply.strip()
    return None


# The generated code runs with stdout captured, so whatever it prints cannot be mistaken for the
# verdict; the verdict is a line carrying a per-run random token, printed after it has finished.
_HARNESS = """
import contextlib, io, json, sys

_CODE = {code}
_FUNCTION = {function}
_CASES = json.loads({cases})
_TOKEN = {token}

def _verdict(passed, total, error=None):
    print(_TOKEN + json.dumps({{"passed": passed, "total": total, "error": error}}))

_namespace = {{"__name__": "__bench__"}}
try:
    with contextlib.redirect_stdout(io.StringIO()):
        exec(compile(_CODE, "<generated>", "exec"), _namespace)
except BaseException as exc:
    _verdict(0, len(_CASES), "load: " + type(exc).__name__)
    sys.exit(0)

_fn = _namespace.get(_FUNCTION)
if not callable(_fn):
    _verdict(0, len(_CASES), "missing function " + _FUNCTION)
    sys.exit(0)

_passed = 0
for _args, _expected in _CASES:
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            _got = _fn(*_args)
        if isinstance(_expected, dict) and "__raises__" in _expected:
            continue  # it returned instead of raising
        if json.loads(json.dumps(_got)) == _expected:
            _passed += 1
    except BaseException as exc:
        if isinstance(_expected, dict) and _expected.get("__raises__") == type(exc).__name__:
            _passed += 1
_verdict(_passed, len(_CASES))
"""


def build_program(task: Task, code: str, token: str | None = None) -> tuple[str, str]:
    """(program, token): the program prints one line `token + json` at the end."""
    token = token or MARKER + secrets.token_hex(8) + ":"
    program = _HARNESS.format(
        code=repr(code),
        function=repr(task.function),
        # JSON is not Python source (true/false/null): ship it as a string and parse it there
        cases=repr(json.dumps([[list(args), expected] for args, expected in task.cases])),
        token=repr(token),
    )
    return program, token


@dataclass(frozen=True)
class Verdict:
    passed: int
    total: int
    error: str | None = None


def read_verdict(stdout: str, token: str, total: int) -> Verdict:
    """The verdict line of a run; anything else (crash, timeout, no line) scores zero."""
    for line in reversed(stdout.splitlines()):
        if line.startswith(token):
            try:
                data = json.loads(line[len(token) :])
                passed, found = int(data["passed"]), int(data["total"])
            except (ValueError, KeyError, TypeError):
                break
            if found != total or not 0 <= passed <= total:
                break
            error = data.get("error")
            return Verdict(passed, total, str(error) if error else None)
    return Verdict(0, total, "no verdict")
