"""Language-model backends: the gateway's model list follows the installed modules."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest
import yaml

from cobble.module_manager.llm import EMPTY, FileGateway, LlmEntry, render_models
from cobble.module_manager.manager import ModuleOperationFailed
from cobble.module_manager.runner import RunnerError

from .test_module_manager import OLLAMA, Rig

ENTRY = LlmEntry(
    "coder-small", "ollama_chat/qwen2.5-coder:1.5b", "http://cobble-ollama-ollama:11434"
)


def test_the_include_file_lists_one_free_deployment_per_model() -> None:
    parsed = yaml.safe_load(render_models([ENTRY]))
    assert parsed == {
        "model_list": [
            {
                "model_name": "coder-small",
                "litellm_params": {
                    "model": "ollama_chat/qwen2.5-coder:1.5b",
                    "api_base": "http://cobble-ollama-ollama:11434",
                    "input_cost_per_token": 0,
                    "output_cost_per_token": 0,
                },
            }
        ]
    }
    assert yaml.safe_load(render_models([])) == {"model_list": []} and render_models([]) == EMPTY


def test_the_file_is_the_same_whatever_the_order() -> None:
    other = LlmEntry("another", "ollama_chat/other", "http://x:1")
    assert render_models([ENTRY, other]) == render_models([other, ENTRY])


def test_hostile_values_stay_data() -> None:
    entry = LlmEntry("x", "ollama/a\nmodel_list: []", "http://h:1\nexec: boom")
    parsed = yaml.safe_load(render_models([entry]))
    assert list(parsed) == ["model_list"] and len(parsed["model_list"]) == 1
    assert parsed["model_list"][0]["litellm_params"]["model"] == "ollama/a\nmodel_list: []"


class Gateway:
    def __init__(self, tmp: Path, live: bool = True) -> None:
        self.path = tmp / "generated" / "models.yaml"
        self.restarts = 0
        self.live = live
        self.seen: list[str] = []
        self.fail_restart = False
        self.gateway = FileGateway(self.path, self.restart, self.is_live)

    def restart(self) -> None:
        self.restarts += 1
        self.seen.append(self.path.read_text())
        if self.fail_restart:
            raise RunnerError("llm_failed")

    def is_live(self) -> bool:
        return self.live


def test_a_new_list_is_written_then_the_gateway_restarts_and_is_awaited(tmp_path: Path) -> None:
    g = Gateway(tmp_path)
    g.gateway.sync([ENTRY])
    assert g.restarts == 1
    assert g.seen == [render_models([ENTRY])]  # the file was in place when it restarted
    assert g.path.read_text() == render_models([ENTRY])


def test_an_unchanged_list_does_not_restart_the_gateway(tmp_path: Path) -> None:
    g = Gateway(tmp_path)
    g.gateway.sync([ENTRY])
    g.gateway.sync([ENTRY])
    assert g.restarts == 1


def test_the_first_empty_list_creates_the_file_without_restarting_for_nothing(
    tmp_path: Path,
) -> None:
    g = Gateway(tmp_path)
    g.gateway.sync([])
    assert g.path.read_text() == EMPTY


def test_a_gateway_that_does_not_come_back_gets_the_previous_list_back(tmp_path: Path) -> None:
    g = Gateway(tmp_path)
    g.gateway.sync([ENTRY])
    g.live = False
    other = LlmEntry("another", "ollama_chat/other", "http://x:1")
    with pytest.raises(RunnerError):
        g.gateway.sync([ENTRY, other])
    assert g.path.read_text() == render_models([ENTRY])
    assert g.restarts == 3  # the attempt, then the restart that restores the last good list


def test_a_failed_restart_restores_too(tmp_path: Path) -> None:
    g = Gateway(tmp_path)
    g.gateway.sync([ENTRY])
    g.fail_restart = True
    with pytest.raises(RunnerError):
        g.gateway.sync([])
    assert g.path.read_text() == render_models([ENTRY])


# --- in the lifecycle ---------------------------------------------------------------------------


class RecordingGateway:
    def __init__(self) -> None:
        self.calls: list[list[LlmEntry]] = []
        self.fail = False

    def sync(self, entries: Sequence[LlmEntry]) -> None:
        if self.fail:
            raise RunnerError("llm_failed")
        self.calls.append(list(entries))

    @property
    def models(self) -> list[str]:
        return [e.name for e in self.calls[-1]] if self.calls else []


def rig(gateway: RecordingGateway) -> Rig:
    return Rig(modules=[OLLAMA], llm=gateway)


def test_installing_a_backend_gives_its_models_to_the_gateway() -> None:
    gateway = RecordingGateway()
    r = rig(gateway)
    r.manager.install(["ollama"])
    assert gateway.models == ["coder-small"]  # the cpu flavour: Rig has 16 GB and no GPU
    assert gateway.calls[-1][0].api_base == "http://cobble-ollama-ollama:11434"


def test_a_gpu_flavour_serves_its_own_models() -> None:
    gateway = RecordingGateway()
    r = Rig(modules=[OLLAMA], llm=gateway, hardware_gpu="nvidia")
    r.manager.install(["ollama"])
    assert gateway.models == ["coder"]


def test_uninstalling_the_backend_empties_the_list() -> None:
    gateway = RecordingGateway()
    r = rig(gateway)
    r.manager.install(["ollama"])
    r.manager.uninstall(["ollama"])
    assert gateway.models == []


def test_a_gateway_that_refuses_rolls_the_install_back() -> None:
    gateway = RecordingGateway()
    gateway.fail = True
    r = rig(gateway)
    with pytest.raises(ModuleOperationFailed) as caught:
        r.manager.install(["ollama"])
    assert (caught.value.step, caught.value.code) == ("gateway", "llm_failed")
    assert r.counts() == {"modules": 0, "secrets": 0, "links": 0}
    assert r.runner.running == {}


def test_a_module_without_models_never_touches_the_gateway() -> None:
    from .test_module_manager import FORGEJO

    gateway = RecordingGateway()
    r = Rig(modules=[FORGEJO], llm=gateway)
    r.manager.install(["forgejo"])
    # only the final quiet sync reaches it, with nothing to add
    assert gateway.calls == [[]]


def test_the_hooks_of_a_backend_know_what_to_fetch_for_the_chosen_flavour() -> None:
    r = Rig(modules=[OLLAMA], hardware_gpu="nvidia")
    r.manager.install(["ollama"])
    facts = r.manager._own_facts("ollama")
    assert facts == {"COBBLE_VARIANT": "nvidia", "COBBLE_LLM_PULL": "qwen2.5-coder:7b"}
    cpu = Rig(modules=[OLLAMA])
    cpu.manager.install(["ollama"])
    assert cpu.manager._own_facts("ollama")["COBBLE_LLM_PULL"] == "qwen2.5-coder:1.5b"


# --- finding and restarting the gateway through the Docker CLI ----------------------------------


@pytest.fixture
def stub_docker(tmp_path: Path) -> Path:
    """A `docker` that answers from files next to it and logs its arguments."""
    script = tmp_path / "docker"
    script.write_text(
        "#!/usr/bin/env bash\n"
        f'echo "$*" >> "{tmp_path}/calls"\n'
        'case "$1" in\n'
        f'  ps) cat "{tmp_path}/ids" 2>/dev/null ;;\n'
        f'  inspect) cat "{tmp_path}/health" 2>/dev/null ;;\n'
        f'  restart) exit "$(cat "{tmp_path}/restart_rc" 2>/dev/null || echo 0)" ;;\n'
        "esac\n"
    )
    script.chmod(0o755)
    return script


def _calls(stub: Path) -> list[str]:
    return (stub.parent / "calls").read_text().splitlines()


def test_the_gateway_is_the_one_container_of_the_service_on_the_shared_network(
    stub_docker: Path,
) -> None:
    from cobble.module_manager.llm import docker_gateway

    root = stub_docker.parent
    (root / "ids").write_text("abc123\n")
    (root / "health").write_text("healthy\n")
    gateway = docker_gateway(
        root / "gen" / "models.yaml", docker=str(stub_docker), live_timeout_s=2
    )
    gateway.sync([ENTRY])
    calls = _calls(stub_docker)
    assert (
        calls[0]
        == "ps -q --filter label=com.docker.compose.service=litellm --filter network=cobble_core"
    )
    assert "restart abc123" in calls
    assert any(c.startswith("inspect -f {{.State.Health.Status}} abc123") for c in calls)


@pytest.mark.parametrize("ids", ["", "one\ntwo\n"])
def test_no_gateway_or_several_is_refused_instead_of_guessing(stub_docker: Path, ids: str) -> None:
    from cobble.module_manager.llm import docker_gateway

    root = stub_docker.parent
    (root / "ids").write_text(ids)
    gateway = docker_gateway(root / "models.yaml", docker=str(stub_docker), live_timeout_s=0.2)
    with pytest.raises(RunnerError) as caught:
        gateway.sync([ENTRY])
    assert caught.value.code == "llm_failed"
    assert not any(c.startswith("restart") for c in _calls(stub_docker))  # nothing was restarted


def test_a_gateway_that_never_turns_healthy_is_rolled_back(stub_docker: Path) -> None:
    from cobble.module_manager.llm import docker_gateway

    root = stub_docker.parent
    (root / "ids").write_text("abc123\n")
    (root / "health").write_text("starting\n")
    path = root / "models.yaml"
    path.write_text(EMPTY)
    gateway = docker_gateway(path, docker=str(stub_docker), live_timeout_s=0.3)
    with pytest.raises(RunnerError):
        gateway.sync([ENTRY])
    assert path.read_text() == EMPTY
