import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import make_agent_cassettes as agents

MARKER = re.compile(r"\[cobble-task:[^\]\s]+\]")


def test_committed_cassettes_and_tree_are_up_to_date() -> None:
    assert agents.main(["--check"]) == 0


def test_every_task_has_its_cassettes() -> None:
    names = {p.name for p in agents.CASSETTES.glob(f"{agents.PREFIX}*.json")}
    for step in agents.load_steps():
        assert f"{agents.PREFIX}{step.ref}-worker-1.json" in names
        writer = f"{agents.PREFIX}{step.ref}-test-writer-1.json" in names
        assert writer is step.writer, step.ref  # demo tasks have no test-writer
    assert f"{agents.PREFIX}X-LOOP-worker-4.json" in names


def test_cassette_shape() -> None:
    for path in agents.CASSETTES.glob(f"{agents.PREFIX}*.json"):
        data = json.loads(path.read_text("utf-8"))
        assert data["version"] == 1
        marker = data["match"]["marker"]
        assert MARKER.fullmatch(marker)
        assert (
            path.name
            == f"{agents.PREFIX}{marker[len('[cobble-task:') : -1].replace(':', '-')}.json"
        )
        content = data["response"]["content"]
        assert content.strip()
        assert "```" in content or "````" in content or "<source>" in content


def test_shared_files_are_ordered_by_dependencies() -> None:
    agents.check_shared_files(agents.load_steps())


def test_unordered_tasks_sharing_a_file_are_rejected() -> None:
    a = agents.Step("T-1", "a", "M1", (), ("x.py",), "plan", True)
    b = agents.Step("T-2", "b", "M1", (), ("x.py",), "plan", True)
    try:
        agents.check_shared_files([a, b])
    except agents.SolutionError as exc:
        assert "x.py" in str(exc)
    else:
        raise AssertionError("expected a SolutionError")


def test_fence_grows_when_a_file_contains_one() -> None:
    assert agents.choose_fence(["plain\n"]) == ("```", "```")
    assert agents.choose_fence(["```\ncode\n```\n"]) == ("````", "````")


def test_whole_format_round_trip() -> None:
    files = {"a.md": "x\n", "b/c.py": "print(1)\n"}
    fence = agents.choose_fence([])
    reply = agents.render_reply("Ok.", files, fence)
    assert agents.parse_reply(reply, fence, list(files)) == files
