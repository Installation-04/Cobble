"""The module-manager lifecycle, with a fake runner: install, uninstall, rollback, recovery."""

from __future__ import annotations

import copy
from collections.abc import Callable
from typing import Any

import pytest
from cobble_sdk import Hardware, Manifest, NeedsConfirmation, parse_manifest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from cobble.db.base import Base
from cobble.db.models import Module, ModuleEvent, ModuleLink, ModuleSecret, PlatformState
from cobble.module_manager.catalog_source import MemoryCatalog
from cobble.module_manager.manager import ModuleManager, ModuleOperationFailed
from cobble.module_manager.runner import FakeRunner, SimulatedCrash
from cobble.module_manager.secret_store import SecretStore
from cobble.module_manager.vault import Vault, VaultError

DIGEST = "d" * 64
ROOT = "/cat"


def manifest(module_id: str, **fields: Any) -> Manifest:
    data: dict[str, Any] = {
        "id": module_id,
        "name": module_id,
        "version": "1.0.0",
        "category": "test",
        "description": {"fr": "Module de test", "en": "Test module"},
        "license": "MIT",
        "images": [f"example.org/{module_id}:1@sha256:{DIGEST}"],
    }
    data.update(fields)
    return parse_manifest(data)


FORGEJO = manifest(
    "forgejo",
    provides=["git"],
    exclusive=["git"],
    secrets=["admin_password", "api_token"],
    core_secrets=["api_token"],
    link_secrets=["admin_password"],
    web_ui={"service": "forgejo", "port": 3000, "path": "/git"},
    hooks={
        "post_install": "hooks/post.sh",
        "register_core": "hooks/register.sh",
        "on_link": {"git": "hooks/oauth.sh"},
        "on_unlink": {"git": "hooks/unoauth.sh"},
    },
)
GITEA = manifest("gitea", provides=["git"], exclusive=["git"])
WOODPECKER = manifest(
    "woodpecker",
    provides=["ci"],
    requires=["git"],
    secrets=["agent_secret"],
    web_ui={"service": "server", "port": 8000, "path": "/ci"},
    hooks={
        "pre_up": "hooks/pre-up.sh",
        "pre_uninstall": "hooks/pre-uninstall.sh",
        "on_link": {"git": "hooks/link-git.sh"},
        "on_unlink": {"git": "hooks/unlink-git.sh"},
    },
)
OLLAMA = manifest(
    "ollama",
    provides=["llm-backend"],
    variants=[
        {
            "id": "nvidia",
            "gpu": "nvidia",
            "models": [
                {
                    "name": "coder",
                    "model": "ollama_chat/qwen2.5-coder:7b",
                    "pull": "qwen2.5-coder:7b",
                }
            ],
        },
        {"id": "cpu", "gpu": "none", "min_ram_mb": 4096},
    ],
    llm={
        "service": "ollama",
        "port": 11434,
        "models": [
            {
                "name": "coder-small",
                "model": "ollama_chat/qwen2.5-coder:1.5b",
                "pull": "qwen2.5-coder:1.5b",
            }
        ],
    },
)
GPU_ONLY = manifest("gpu-only", hardware={"gpu": "nvidia"})

SCRIPTS = {
    "post": f"{ROOT}/forgejo/hooks/post.sh",
    "register": f"{ROOT}/forgejo/hooks/register.sh",
    "oauth": f"{ROOT}/forgejo/hooks/oauth.sh",
    "unoauth": f"{ROOT}/forgejo/hooks/unoauth.sh",
    "pre-up": f"{ROOT}/woodpecker/hooks/pre-up.sh",
    "pre-uninstall": f"{ROOT}/woodpecker/hooks/pre-uninstall.sh",
    "link-git": f"{ROOT}/woodpecker/hooks/link-git.sh",
    "unlink-git": f"{ROOT}/woodpecker/hooks/unlink-git.sh",
}

MASTER = bytes(range(32))


class Rig:
    def __init__(
        self,
        modules: list[Manifest] | None = None,
        hardware: Hardware | None = None,
        store: SecretStore | None = None,
        edge: Any = None,
        llm: Any = None,
        hardware_gpu: str = "none",
    ) -> None:
        engine = create_engine(
            "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
        )
        Base.metadata.create_all(engine)
        self.sessions: Callable[[], Session] = sessionmaker(engine, expire_on_commit=False)
        self.catalog = MemoryCatalog({m.id: m for m in modules or [FORGEJO, WOODPECKER]}, root=ROOT)
        self.runner = FakeRunner()
        self.store = store or SecretStore(Vault({1: MASTER}))
        self.manager = ModuleManager(
            self.sessions,
            self.catalog,
            self.runner,
            self.store,
            hardware or Hardware(ram_mb=16384, gpu=hardware_gpu),  # type: ignore[arg-type]
            edge=edge,
            llm=llm,
        )

    def modules(self) -> dict[str, Module]:
        with self.sessions() as s:
            return {m.id: m for m in s.scalars(select(Module))}

    def counts(self) -> dict[str, int]:
        with self.sessions() as s:
            return {
                "modules": len(s.scalars(select(Module)).all()),
                "secrets": len(s.scalars(select(ModuleSecret)).all()),
                "links": len(s.scalars(select(ModuleLink)).all()),
            }

    def events(self) -> list[ModuleEvent]:
        with self.sessions() as s:
            return list(s.scalars(select(ModuleEvent).order_by(ModuleEvent.at)))

    def generation(self) -> int:
        with self.sessions() as s:
            state = s.get(PlatformState, 1)
            return state.modules_generation if state else 0


# --- happy paths ------------------------------------------------------------------------------


def test_install_one_module() -> None:
    rig = Rig()
    plan = rig.manager.install(["forgejo"])
    assert [s.module for s in plan.steps] == ["forgejo"]
    forgejo = rig.modules()["forgejo"]
    assert (forgejo.state, forgejo.explicit) == ("running", True)
    assert set(rig.runner.running) == {"cobble-forgejo"}
    compose = rig.runner.running["cobble-forgejo"]
    assert compose["name"] == "cobble-forgejo"
    assert all("ports" not in svc for svc in compose["services"].values())
    with rig.sessions() as s:
        assert rig.store.keys(s, "forgejo") == ["admin_password", "api_token"]
    assert rig.generation() == 1
    steps = [e.step for e in rig.events() if e.kind == "install"]
    assert steps == [
        "record",
        "hardware",
        "secrets",
        "pre_up",
        "render",
        "up",
        "post_install",
        "register_core",
        "health",
        "route",
        "gateway",
        "link",
    ]


def test_installing_a_consumer_pulls_in_its_provider_and_links_them() -> None:
    rig = Rig()
    plan = rig.manager.install(["woodpecker"])
    assert [s.module for s in plan.steps] == ["forgejo", "woodpecker"]
    modules = rig.modules()
    assert modules["forgejo"].explicit is False  # only a dependency
    assert modules["woodpecker"].explicit is True
    with rig.sessions() as s:
        link = s.scalars(select(ModuleLink)).one()
        assert (link.consumer, link.provider, link.capability, link.state) == (
            "woodpecker", "forgejo", "git", "linked",
        )  # fmt: skip
    link_hooks = [
        (script, env)
        for script, env in rig.runner.hook_envs
        if "oauth" in script or "link-git" in script
    ]
    assert [script for script, _ in link_hooks] == [
        SCRIPTS["oauth"],
        SCRIPTS["link-git"],
    ]  # provider first
    provider_env, consumer_env = link_hooks[0][1], link_hooks[1][1]
    assert provider_env["COBBLE_LINK_ROLE"] == "provider"
    assert provider_env["COBBLE_LINK_PEER"] == "woodpecker"
    assert provider_env["COBBLE_PEER_HOST"] == "cobble-woodpecker-server"
    assert consumer_env["COBBLE_LINK_ROLE"] == "consumer"
    assert consumer_env["COBBLE_PEER_HOST"] == "cobble-forgejo-forgejo"
    assert "COBBLE_SECRET_API_TOKEN" in provider_env  # a hook sees its own module's secrets
    assert "COBBLE_SECRET_AGENT_SECRET" not in provider_env


def test_installing_the_provider_afterwards_only_marks_it_explicit() -> None:
    rig = Rig()
    rig.manager.install(["woodpecker"])
    calls = len(rig.runner.calls)
    plan = rig.manager.install(["forgejo"])
    assert plan.steps == ()
    assert len(rig.runner.calls) == calls  # nothing was started
    assert rig.modules()["forgejo"].explicit is True


def test_installing_twice_is_a_no_op() -> None:
    rig = Rig()
    rig.manager.install(["woodpecker"])
    calls, generation = len(rig.runner.calls), rig.generation()
    assert rig.manager.install(["woodpecker"]).steps == ()
    assert len(rig.runner.calls) == calls
    assert rig.generation() == generation


def test_hook_produced_secrets_are_stored_for_the_module_that_ran_the_hook() -> None:
    rig = Rig()
    rig.runner.hook_secrets[SCRIPTS["register"]] = {"service_token": "tok-from-the-hook-123"}
    rig.manager.install(["forgejo"])
    with rig.sessions() as s:
        value = rig.store.get(s, "forgejo", "service_token")
        assert value is not None
        assert value.reveal() == "tok-from-the-hook-123"


def test_no_secret_value_reaches_the_event_history() -> None:
    rig = Rig()
    rig.runner.hook_secrets[SCRIPTS["register"]] = {"service_token": "tok-from-the-hook-123"}
    rig.manager.install(["woodpecker"])
    with rig.sessions() as s:
        values = [
            v.reveal()
            for (module, key) in [
                ("forgejo", "api_token"),
                ("forgejo", "service_token"),
                ("woodpecker", "agent_secret"),
            ]
            if (v := rig.store.get(s, module, key)) is not None
        ]
    assert len(values) == 3
    history = repr([(e.module_id, e.kind, e.step, e.code, e.params) for e in rig.events()])
    assert not any(value in history for value in values)


# --- uninstall --------------------------------------------------------------------------------


def test_uninstalling_the_consumer_removes_the_dependency_it_pulled_in() -> None:
    rig = Rig()
    rig.manager.install(["woodpecker"])
    plan = rig.manager.uninstall(["woodpecker"])
    assert [(s.action, s.module) for s in plan.steps] == [
        ("uninstall", "woodpecker"), ("uninstall", "forgejo")
    ]  # fmt: skip
    assert rig.counts() == {"modules": 0, "secrets": 0, "links": 0}
    assert rig.runner.running == {}
    assert rig.runner.volumes == set()
    hooks = [script for script, _ in rig.runner.hook_envs]
    assert SCRIPTS["unoauth"] in hooks and SCRIPTS["unlink-git"] in hooks
    assert hooks.index(SCRIPTS["unlink-git"]) < len(hooks)  # unlink hooks ran before the removal
    downs = [name for op, name in rig.runner.calls if op == "down"]
    assert downs == ["cobble-woodpecker", "cobble-forgejo"]


def test_uninstalling_a_provider_needs_the_cascade_to_be_confirmed() -> None:
    rig = Rig()
    rig.manager.install(["forgejo", "woodpecker"])
    with pytest.raises(NeedsConfirmation) as info:
        rig.manager.uninstall(["forgejo"])
    assert info.value.cascade == ("woodpecker",)
    assert set(rig.modules()) == {"forgejo", "woodpecker"}  # nothing happened
    rig.manager.uninstall(["forgejo"], confirm_cascade=True)
    assert rig.counts() == {"modules": 0, "secrets": 0, "links": 0}


def test_a_failing_unlink_hook_never_blocks_a_removal() -> None:
    rig = Rig()
    rig.manager.install(["woodpecker"])
    rig.runner.fail |= {("hook", SCRIPTS["unoauth"]), ("hook", SCRIPTS["unlink-git"])}
    rig.manager.uninstall(["woodpecker"])
    assert rig.counts() == {"modules": 0, "secrets": 0, "links": 0}
    assert any(e.outcome == "error" and e.kind == "unlink" for e in rig.events())


def test_a_failing_down_marks_the_module_failed_and_recover_finishes_the_job() -> None:
    rig = Rig()
    rig.manager.install(["forgejo"])
    rig.runner.fail.add(("down", "cobble-forgejo"))
    with pytest.raises(ModuleOperationFailed) as info:
        rig.manager.uninstall(["forgejo"])
    assert (info.value.step, info.value.code) == ("down", "down_failed")
    assert rig.modules()["forgejo"].state == "failed"
    rig.runner.fail.clear()
    assert rig.manager.recover() == ["forgejo"]
    assert rig.counts() == {"modules": 0, "secrets": 0, "links": 0}


# --- rollback: a failure at any step leaves nothing behind -----------------------------------


def _fail_runner(operation: str, name: str) -> Callable[[Rig], None]:
    return lambda rig: rig.runner.fail.add((operation, name))


def _bad_compose(rig: Rig) -> None:
    rig.catalog.composes["woodpecker"] = {
        "services": {"server": {"image": WOODPECKER.images[0], "privileged": True}}
    }


def _failing_vault(rig: Rig) -> None:
    class Failing(SecretStore):
        def generate(self, session: Session, module_id: str, key: str) -> bool:
            if module_id == "woodpecker":
                raise VaultError("decrypt_failed")
            return super().generate(session, module_id, key)

    rig.store = Failing(Vault({1: MASTER}))
    rig.manager._store = rig.store


_forgejo_unhealthy = _fail_runner("health", "cobble-forgejo")


def _hook(script: str) -> Callable[[Rig], None]:
    return _fail_runner("hook", SCRIPTS[script])


FAULTS: list[tuple[str, Callable[[Rig], None], str, str, str]] = [
    # (name, injection, failing module, failing step, code)
    ("secrets", _failing_vault, "woodpecker", "secrets", "decrypt_failed"),
    ("render", _bad_compose, "woodpecker", "render", "compose_rejected"),
    ("up", _fail_runner("up", "cobble-woodpecker"), "woodpecker", "up", "up_failed"),
    ("health", _fail_runner("health", "cobble-woodpecker"), "woodpecker", "health", "unhealthy"),
    ("pre_up of the consumer", _hook("pre-up"), "woodpecker", "pre_up", "hook_failed"),
    ("link, provider side", _hook("oauth"), "forgejo", "on_link", "hook_failed"),
    ("link, consumer side", _hook("link-git"), "woodpecker", "on_link", "hook_failed"),
    ("first module: up", _fail_runner("up", "cobble-forgejo"), "forgejo", "up", "up_failed"),
    ("first module: post_install", _hook("post"), "forgejo", "post_install", "hook_failed"),
    ("first module: register_core", _hook("register"), "forgejo", "register_core", "hook_failed"),
    (
        "first module: health",
        _fail_runner("health", "cobble-forgejo"),
        "forgejo",
        "health",
        "unhealthy",
    ),
]


@pytest.mark.parametrize(
    ("inject", "module", "step", "code"), [f[1:] for f in FAULTS], ids=[f[0] for f in FAULTS]
)
def test_a_failure_rolls_back_the_whole_plan(
    inject: Callable[[Rig], None], module: str, step: str, code: str
) -> None:
    rig = Rig()
    inject(rig)
    with pytest.raises(ModuleOperationFailed) as info:
        rig.manager.install(["woodpecker"])
    failure = info.value
    assert (failure.module, failure.step, failure.code) == (module, step, code)
    assert failure.partial is False
    # nothing is left: no rows, secrets or links, nothing running, no volume
    assert rig.counts() == {"modules": 0, "secrets": 0, "links": 0}
    assert rig.runner.running == {}
    assert rig.runner.volumes == set()
    # the failure and the rollback are in the history, without any detail that could leak
    events = rig.events()
    assert any(e.outcome == "error" and e.code == code for e in events)
    assert any(e.kind == "rollback" for e in events) or (module == "forgejo" and step == "record")


def test_a_failed_install_can_be_retried() -> None:
    rig = Rig()
    rig.runner.fail.add(("up", "cobble-woodpecker"))
    with pytest.raises(ModuleOperationFailed):
        rig.manager.install(["woodpecker"])
    rig.runner.fail.clear()
    rig.manager.install(["woodpecker"])
    assert {m.state for m in rig.modules().values()} == {"running"}


def test_a_failing_rollback_marks_the_module_failed_and_still_reports_the_cause() -> None:
    rig = Rig()
    rig.runner.fail |= {("up", "cobble-woodpecker"), ("down", "cobble-forgejo")}
    with pytest.raises(ModuleOperationFailed) as info:
        rig.manager.install(["woodpecker"])
    assert (info.value.module, info.value.step) == ("woodpecker", "up")
    assert info.value.rolled_back == ("woodpecker",)  # forgejo could not be rolled back
    modules = rig.modules()
    assert set(modules) == {"forgejo"}
    assert modules["forgejo"].state == "failed"
    rig.runner.fail.clear()
    assert rig.manager.recover() == ["forgejo"]
    assert rig.counts() == {"modules": 0, "secrets": 0, "links": 0}


def test_the_generation_counter_only_moves_when_modules_change() -> None:
    rig = Rig()
    rig.manager.install(["forgejo"])
    first = rig.generation()
    rig.runner.fail.add(("up", "cobble-woodpecker"))
    with pytest.raises(ModuleOperationFailed):
        rig.manager.install(["woodpecker"])
    assert rig.generation() >= first  # never goes backwards
    rig.runner.fail.clear()
    rig.manager.install(["woodpecker"])
    assert rig.generation() > first


# --- crash recovery ---------------------------------------------------------------------------


def test_recover_cleans_up_an_install_interrupted_by_a_crash() -> None:
    rig = Rig()
    rig.runner.crash.add(("up", "cobble-woodpecker"))
    with pytest.raises(SimulatedCrash):
        rig.manager.install(["woodpecker"])
    states = {m.id: m.state for m in rig.modules().values()}
    assert states == {"forgejo": "running", "woodpecker": "installing"}
    rig.runner.crash.clear()
    assert rig.manager.recover() == ["woodpecker"]
    assert {m.id: m.state for m in rig.modules().values()} == {"forgejo": "running"}
    rig.manager.install(["woodpecker"])  # and the install can simply be run again
    assert set(rig.modules()) == {"forgejo", "woodpecker"}


def test_recover_finishes_an_uninstall_interrupted_by_a_crash() -> None:
    rig = Rig()
    rig.manager.install(["forgejo"])
    rig.runner.crash.add(("down", "cobble-forgejo"))
    with pytest.raises(SimulatedCrash):
        rig.manager.uninstall(["forgejo"])
    assert rig.modules()["forgejo"].state == "removing"
    rig.runner.crash.clear()
    assert rig.manager.recover() == ["forgejo"]
    assert rig.counts() == {"modules": 0, "secrets": 0, "links": 0}


def test_recover_does_nothing_when_nothing_was_interrupted() -> None:
    rig = Rig()
    rig.manager.install(["forgejo"])
    assert rig.manager.recover() == []
    assert rig.modules()["forgejo"].state == "running"


# --- hardware and replacement -----------------------------------------------------------------


def test_the_variant_is_chosen_for_the_machine() -> None:
    nvidia = Rig([OLLAMA], Hardware(ram_mb=16384, gpu="nvidia"))
    nvidia.manager.install(["ollama"])
    assert nvidia.modules()["ollama"].variant == "nvidia"
    cpu = Rig([OLLAMA], Hardware(ram_mb=16384))
    cpu.manager.install(["ollama"])
    assert cpu.modules()["ollama"].variant == "cpu"


def test_a_module_that_does_not_fit_the_machine_fails_at_the_hardware_step() -> None:
    rig = Rig([GPU_ONLY], Hardware(ram_mb=16384))
    with pytest.raises(ModuleOperationFailed) as info:
        rig.manager.install(["gpu-only"])
    assert (info.value.step, info.value.code) == ("hardware", "no_compatible_variant")
    assert rig.counts() == {"modules": 0, "secrets": 0, "links": 0}


def test_replacing_a_provider_uninstalls_the_old_one_first() -> None:
    rig = Rig([FORGEJO, GITEA, WOODPECKER])
    rig.manager.install(["forgejo", "woodpecker"])
    plan = rig.manager.install(["gitea"], replace=True)
    assert [(s.action, s.module) for s in plan.steps] == [
        ("uninstall", "forgejo"),
        ("install", "gitea"),
    ]
    modules = rig.modules()
    assert set(modules) == {"gitea", "woodpecker"}
    with rig.sessions() as s:
        assert s.scalars(select(ModuleLink.provider)).all() == ["gitea"]  # relinked


def test_a_failed_replacement_reports_that_the_uninstall_was_not_undone() -> None:
    rig = Rig([FORGEJO, GITEA, WOODPECKER])
    rig.manager.install(["forgejo"])
    rig.runner.fail.add(("up", "cobble-gitea"))
    with pytest.raises(ModuleOperationFailed) as info:
        rig.manager.install(["gitea"], replace=True)
    assert info.value.partial is True
    assert set(rig.modules()) == set()  # forgejo is gone, gitea was rolled back


def test_the_plan_can_be_previewed_without_side_effects() -> None:
    rig = Rig()
    plan = rig.manager.plan_install(["woodpecker"])
    assert [s.module for s in plan.steps] == ["forgejo", "woodpecker"]
    assert rig.counts() == {"modules": 0, "secrets": 0, "links": 0}
    assert rig.runner.calls == []
    rig.manager.install(["woodpecker"])
    assert [s.module for s in rig.manager.plan_uninstall(["woodpecker"]).steps] == [
        "woodpecker", "forgejo"
    ]  # fmt: skip


def test_provider_choices_survive_between_operations() -> None:
    """A dependency chosen earlier is remembered from what is installed, not asked again."""
    rig = Rig([FORGEJO, GITEA, WOODPECKER])
    with pytest.raises(Exception, match="choose a provider"):
        rig.manager.install(["woodpecker"])  # two git providers: the caller must choose
    rig.manager.install(["woodpecker"], {"git": "gitea"})
    other = copy.copy(rig)
    assert other.manager.plan_uninstall(["woodpecker"]).steps[-1].module == "gitea"
    assert rig.manager.install(["woodpecker"]).steps == ()  # no new question


def test_modules_receive_the_platform_facts_in_compose_and_hooks() -> None:
    rig = Rig()
    rig.manager._platform_env = {"COBBLE_PUBLIC_URL": "http://box", "COBBLE_PUBLIC_HOST": "box"}
    rig.manager.install(["forgejo"])
    envs = [env for _, env in rig.runner.hook_envs]
    assert envs and all(env["COBBLE_PUBLIC_URL"] == "http://box" for env in envs)
    assert all(env["COBBLE_MODULE_ID"] == "forgejo" for env in envs)


def test_a_hook_before_start_sees_the_provider_it_requires_and_what_it_shares() -> None:
    rig = Rig()
    rig.runner.hook_secrets[SCRIPTS["pre-up"]] = {"forgejo_client": "client-1"}
    rig.manager.install(["woodpecker"])
    pre_up = [env for script, env in rig.runner.hook_envs if script == SCRIPTS["pre-up"]]
    assert len(pre_up) == 1
    env = pre_up[0]
    assert env["COBBLE_PEER_GIT_MODULE"] == "forgejo"
    assert env["COBBLE_PEER_GIT_HOST"] == "cobble-forgejo-forgejo"
    assert env["COBBLE_PEER_GIT_PORT"] == "3000"
    with rig.sessions() as session:
        shared = rig.store.get(session, "forgejo", "admin_password")
    assert shared is not None and env["COBBLE_PEER_GIT_SECRET_ADMIN_PASSWORD"] == shared.reveal()
    # only what the provider lists in link_secrets is shared: its api_token (core) is not
    assert not any(key.endswith("SECRET_API_TOKEN") for key in env)
    # what the hook printed belongs to the consumer and is in the environment of its compose file
    with rig.sessions() as session:
        stored = rig.store.get(session, "woodpecker", "forgejo_client")
    assert stored is not None and stored.reveal() == "client-1"


def test_the_consumer_is_prepared_after_its_provider_is_up() -> None:
    rig = Rig()
    rig.manager.install(["woodpecker"])
    order = [(op, name) for op, name in rig.runner.calls if op in ("up", "hook")]
    assert order.index(("up", "cobble-forgejo")) < order.index(("hook", SCRIPTS["pre-up"]))
    assert order.index(("hook", SCRIPTS["pre-up"])) < order.index(("up", "cobble-woodpecker"))


def test_the_cleanup_hook_of_a_consumer_still_sees_its_provider() -> None:
    rig = Rig()
    rig.manager.install(["forgejo", "woodpecker"])
    rig.manager.uninstall(["woodpecker"])
    cleanup = [env for s, env in rig.runner.hook_envs if s == SCRIPTS["pre-uninstall"]]
    assert cleanup and cleanup[0]["COBBLE_PEER_GIT_HOST"] == "cobble-forgejo-forgejo"
