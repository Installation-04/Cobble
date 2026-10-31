"""Strict plan schema: what the planner must return, and every reason to reject it.

`validate_plan` is the single entry point. The exported JSON Schema lives next to this file in
`plan.schema.json` (regenerate with `python -m cobble.orchestrator.plan_schema`).
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from pydantic_core import ErrorDetails

SCHEMA_PATH = Path(__file__).with_name("plan.schema.json")
MILESTONE_ID = r"^M\d+$"
TASK_ID = r"^T-\d+$"

_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)

Size = Literal["S", "M"]
TaskRole = Literal["backend", "frontend", "fullstack", "devops", "docs"]

_STRICT = ConfigDict(extra="forbid", strict=True)
_Text = Annotated[str, Field(min_length=1)]


class PlanInvalid(Exception):
    """The plan breaks at least one rule. `errors` lists every violation found."""

    def __init__(self, errors: list[str]) -> None:
        super().__init__("; ".join(errors))
        self.errors = errors


def _bad_path(path: str) -> bool:
    return (
        not path.strip()
        or path.startswith(("/", "\\"))
        or bool(re.match(r"^[A-Za-z]:", path))
        or ".." in re.split(r"[/\\]", path)
    )


class Milestone(BaseModel):
    model_config = _STRICT

    id: Annotated[str, Field(pattern=MILESTONE_ID)]
    title: _Text

    @field_validator("title")
    @classmethod
    def _title(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value


class Task(BaseModel):
    model_config = _STRICT

    id: Annotated[str, Field(pattern=TASK_ID)]
    title: _Text
    milestone: Annotated[str, Field(pattern=MILESTONE_ID)]
    depends_on: list[Annotated[str, Field(pattern=TASK_ID)]] = Field(default_factory=list)
    files: Annotated[list[str], Field(min_length=1)]
    acceptance: Annotated[list[str], Field(min_length=1)]
    tests: _Text
    size: Size
    role: TaskRole

    @field_validator("title", "tests")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value

    @field_validator("files")
    @classmethod
    def _files(cls, value: list[str]) -> list[str]:
        bad = [path for path in value if _bad_path(path)]
        if bad:
            raise ValueError(
                f"must be non-empty relative paths without '..' (got {', '.join(map(repr, bad))})"
            )
        return value

    @field_validator("acceptance")
    @classmethod
    def _acceptance(cls, value: list[str]) -> list[str]:
        if any(not item.strip() for item in value):
            raise ValueError("criteria must not be blank")
        return value


class Plan(BaseModel):
    model_config = _STRICT

    milestones: Annotated[list[Milestone], Field(min_length=1)]
    tasks: Annotated[list[Task], Field(min_length=1)]


def _location(loc: tuple[int | str, ...]) -> str:
    out = ""
    for part in loc:
        out += f"[{part}]" if isinstance(part, int) else (f".{part}" if out else str(part))
    return out or "plan"


def _message(error: ErrorDetails) -> str:
    kind = error["type"]
    field = str(error["loc"][-1]) if error["loc"] else ""
    ctx = error.get("ctx") or {}
    if kind == "missing":
        return "is required"
    if kind == "extra_forbidden":
        return "is not an allowed field"
    if kind == "too_short" and field in ("milestones", "tasks"):
        return f"at least one {field[:-1]} is required"
    if kind == "too_short" and field == "acceptance":
        return "at least one acceptance criterion is required"
    if kind == "too_short" and field == "files":
        return "at least one file is required"
    if kind in ("too_short", "string_too_short"):
        return "must not be empty"
    if kind == "literal_error" and field == "size":
        return "must be 'S' or 'M' (split any larger task into smaller ones)"
    if kind == "literal_error" and field == "role":
        return "must be one of backend, frontend, fullstack, devops, docs"
    if kind == "string_pattern_mismatch":
        return f"must match {ctx.get('pattern')}"
    if kind.endswith("_type"):
        return f"has the wrong type ({error['msg'].lower()})"
    return str(error["msg"]).removeprefix("Value error, ")


def _structural_errors(exc: ValidationError) -> list[str]:
    return [f"{_location(e['loc'])}: {_message(e)}" for e in exc.errors()]


def _find_cycles(graph: Mapping[str, list[str]]) -> list[list[str]]:
    cycles: list[list[str]] = []
    state: dict[str, int] = {}  # 1 = on the current path, 2 = done
    path: list[str] = []

    def visit(node: str) -> None:
        state[node] = 1
        path.append(node)
        for nxt in graph.get(node, []):
            if state.get(nxt) == 1:
                cycles.append([*path[path.index(nxt) :], nxt])
            elif nxt not in state and nxt in graph:
                visit(nxt)
        path.pop()
        state[node] = 2

    for node in graph:
        if node not in state:
            visit(node)
    return cycles


def _reference_errors(plan: Plan) -> list[str]:
    errors: list[str] = []
    milestone_ids = [m.id for m in plan.milestones]
    errors += [f"milestones: duplicate id {mid}" for mid in sorted(_duplicates(milestone_ids))]
    task_ids = [t.id for t in plan.tasks]
    errors += [f"tasks: duplicate id {tid}" for tid in sorted(_duplicates(task_ids))]
    for index, task in enumerate(plan.tasks):
        where = f"tasks[{index}] ({task.id})"
        if task.milestone not in milestone_ids:
            errors.append(f"{where}.milestone: unknown milestone {task.milestone}")
        for dep in task.depends_on:
            if dep not in task_ids:
                errors.append(f"{where}.depends_on: unknown task {dep}")
    graph = {t.id: [d for d in t.depends_on if d in task_ids] for t in plan.tasks}
    errors += [f"dependency cycle: {' -> '.join(cycle)}" for cycle in _find_cycles(graph)]
    return errors


def _duplicates(values: list[str]) -> set[str]:
    return {value for value in values if values.count(value) > 1}


def validate_plan(data: Any) -> Plan:
    """Return the parsed plan, or raise `PlanInvalid` listing every violation."""
    try:
        plan = Plan.model_validate(data)
    except ValidationError as exc:
        raise PlanInvalid(_structural_errors(exc)) from None
    errors = _reference_errors(plan)
    if errors:
        raise PlanInvalid(errors)
    return plan


def extract_json(text: str) -> Any:
    """Parse the JSON of a reply: a ```json fenced block, or bare JSON (maybe with chatter)."""
    candidates = [match.strip() for match in _FENCE.findall(text)]
    candidates.append(text.strip())
    start, end = text.find("{"), text.rfind("}")
    if 0 <= start < end:
        candidates.append(text[start : end + 1])
    error = "empty reply"
    for candidate in candidates:
        try:
            return json.loads(candidate)
        except ValueError as exc:
            error = str(exc)
    raise PlanInvalid([f"the reply is not valid JSON ({error})"])


def parse_plan_reply(text: str) -> Plan:
    """Extract the JSON of a planner reply and validate it. Raises `PlanInvalid`."""
    return validate_plan(extract_json(text))


def plan_json_schema() -> dict[str, Any]:
    return Plan.model_json_schema()


def schema_text() -> str:
    return json.dumps(plan_json_schema(), indent=2, sort_keys=True) + "\n"


if __name__ == "__main__":
    SCHEMA_PATH.write_text(schema_text(), encoding="utf-8")
