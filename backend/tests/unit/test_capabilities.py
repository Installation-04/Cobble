from __future__ import annotations

import re
import uuid
from pathlib import Path

import pytest

from cobble.capabilities import AgentOutcome, AgentTask, CIState, MergeRefused, Role
from cobble.capabilities.fakes import (
    FakeAgentRunner,
    FakeCIProvider,
    FakeGitProvider,
    FakeLLMClient,
)

COBBLE = Path(__file__).resolve().parents[2] / "cobble"


def test_merge_is_refused_unless_ci_is_green() -> None:
    ci = FakeCIProvider()
    git = FakeGitProvider(ci)
    repo = git.create_repo_from_template("todo", Path("templates/fastapi-react"))
    ci.activate(repo)
    mr = git.open_merge_request(repo, "task/T-1", "main", "T-1")

    with pytest.raises(MergeRefused):  # no result yet: pending
        git.merge(mr)
    ci.set_result(repo, "task/T-1", CIState.FAILURE)
    with pytest.raises(MergeRefused):
        git.merge(mr)
    assert git.merged == []

    ci.set_result(repo, "task/T-1", CIState.SUCCESS)
    git.merge(mr)
    assert git.merged == [mr]
    git.tag(repo, "milestone-1", "main")
    assert git.tags == [("todo", "milestone-1", "main")]


def test_agent_runner_records_runs_and_stops() -> None:
    runner = FakeAgentRunner(AgentOutcome.LOOP_DETECTED)
    task = AgentTask(uuid.uuid4(), uuid.uuid4(), "fake://x.git", "b", Role.WORKER, "do it")
    assert runner.run(task).outcome is AgentOutcome.LOOP_DETECTED
    run_id = runner.start(task)
    assert runner.poll(run_id) is not None
    runner.stop(run_id)
    assert runner.runs == [task, task]
    assert runner.stopped == [run_id]


def test_fake_llm_client_records_calls() -> None:
    llm = FakeLLMClient(reply="plan")
    result = llm.chat(Role.PLANNER, [{"role": "user", "content": "hi"}])
    assert result.content == "plan"
    assert llm.calls[0][0] is Role.PLANNER


def test_core_never_names_a_product() -> None:
    """Rule 1: the core talks to capabilities, never to Forgejo, Woodpecker, Ollama or Aider."""
    banned = re.compile(r"forgejo|woodpecker|ollama|aider", re.I)
    offenders = [
        str(path.relative_to(COBBLE))
        for path in COBBLE.rglob("*.py")
        if "providers" not in path.parts and banned.search(path.read_text("utf-8"))
    ]
    assert offenders == []
