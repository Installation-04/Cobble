"""Install and uninstall modules: the lifecycle, the rollback and the crash recovery (ADR 0008).

Install, per module:   record -> hardware -> secrets -> render -> up -> post_install ->
                       register_core -> health -> (running) -> link
Uninstall, per module: (removing) -> unlink -> pre_uninstall -> down -> forget

A failure rolls back, in reverse order, every module installed by the same plan and reports the
step and a stable error code. Uninstalls are not undone (a removed module cannot be restored
from here): a plan that fails after uninstalling something says so with `partial=True`.
`recover()` finishes or cleans up whatever a crash left in `installing` or `removing`.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from typing import Any

from cobble_sdk import (
    ComposeRejected,
    Hardware,
    Manifest,
    NoCompatibleVariant,
    Plan,
    Step,
    UnknownModule,
    choose_variant,
    desired_links,
    plan_install,
    plan_uninstall,
    rewrite_compose,
)
from cobble_sdk.resolve import install_order
from cobble_sdk.routes import render_route, upstream
from sqlalchemy import select
from sqlalchemy.orm import Session

from cobble.db.models import Module, ModuleEvent, ModuleLink, PlatformState

from .catalog_source import CatalogSource
from .edge import Edge, NullEdge
from .runner import HookResult, Runner, RunnerError
from .secret_store import SecretStore
from .vault import SecretValue, VaultError

log = logging.getLogger(__name__)

SessionFactory = Callable[[], Session]
EventSink = Callable[[dict[str, Any]], None]


class ModuleOperationFailed(Exception):
    """An install or uninstall failed. `step` and `code` are stable and safe to show."""

    def __init__(
        self,
        module: str,
        step: str,
        code: str,
        *,
        rolled_back: Sequence[str] = (),
        partial: bool = False,
    ) -> None:
        super().__init__(f"{module}: {step}: {code}")
        self.module = module
        self.step = step
        self.code = code
        self.rolled_back = tuple(rolled_back)
        self.partial = partial


class _StepFailed(Exception):
    def __init__(self, module: str, step: str, code: str) -> None:
        super().__init__(f"{module}: {step}: {code}")
        self.module = module
        self.step = step
        self.code = code


def _code_of(exc: Exception) -> str:
    if isinstance(exc, (VaultError, RunnerError)):
        return exc.code
    if isinstance(exc, NoCompatibleVariant):
        return "no_compatible_variant"
    if isinstance(exc, ComposeRejected):
        return "compose_rejected"
    return "internal_error"


def _project(module_id: str) -> str:
    return f"cobble-{module_id}"


class ModuleManager:
    def __init__(
        self,
        sessions: SessionFactory,
        catalog: CatalogSource,
        runner: Runner,
        store: SecretStore,
        hardware: Hardware,
        *,
        health_timeout_s: float = 120.0,
        bus_network: str = "cobble_core",
        on_event: EventSink | None = None,
        edge: Edge | None = None,
        platform_env: Mapping[str, str] | None = None,
    ) -> None:
        self._sessions = sessions
        self._catalog = catalog
        self._runner = runner
        self._store = store
        self._hardware = hardware
        self._health_timeout_s = health_timeout_s
        self._bus_network = bus_network
        self._on_event = on_event
        # Facts about the platform every module may use (public URL...): compose variables and
        # hook environment. Never secrets.
        self._platform_env = dict(platform_env or {})
        self._edge: Edge = edge if edge is not None else NullEdge()
        self._lock = threading.Lock()  # one operation at a time

    # --- reading the state ---------------------------------------------------------------------

    def _manifests(self) -> Mapping[str, Manifest]:
        return self._catalog.manifests()

    def _state(self, session: Session) -> tuple[frozenset[str], dict[str, str]]:
        """The explicit set and the provider choices implied by what is installed."""
        rows = session.scalars(select(Module).where(Module.state == "running")).all()
        manifests = self._manifests()
        explicit = frozenset(r.id for r in rows if r.explicit)
        choices: dict[str, str] = {}
        for row in rows:
            if not row.explicit and row.id in manifests:
                for provided in manifests[row.id].provides:
                    choices.setdefault(provided.capability, row.id)
        return explicit, choices

    # --- read-only views for the service --------------------------------------------------------

    @property
    def hardware(self) -> Hardware:
        return self._hardware

    def catalog(self) -> Mapping[str, Manifest]:
        return self._manifests()

    def states(self) -> dict[str, dict[str, Any]]:
        """Installed modules: state, whether the user asked for them, variant, last error code."""
        with self._sessions() as session:
            return {
                row.id: {
                    "state": row.state,
                    "explicit": row.explicit,
                    "variant": row.variant,
                    "version": row.version,
                    "error": row.last_error,
                }
                for row in session.scalars(select(Module))
            }

    def secret_status(self, module_id: str) -> dict[str, bool]:
        """Which declared secrets are set. Values never leave the vault."""
        manifest = self._manifests().get(module_id)
        if manifest is None:
            raise UnknownModule(module_id)
        with self._sessions() as session:
            return self._store.status(session, module_id, manifest.secrets)

    def connections(self) -> dict[str, dict[str, Any]]:
        """What the core needs to reach each running module: its capabilities, its in-network
        address and the secrets its manifest lists in `core_secrets` (and nothing else)."""
        manifests = self._manifests()
        result: dict[str, dict[str, Any]] = {}
        with self._sessions() as session:
            for row in session.scalars(select(Module).where(Module.state == "running")):
                manifest = manifests.get(row.id)
                if manifest is None:
                    continue
                target = upstream(manifest)
                url = f"http://{target}" if target else ""
                secrets: dict[str, str] = {}
                for key in manifest.core_secrets:
                    value = self._store.get(session, row.id, key)
                    if value is not None:
                        secrets[key] = value.reveal()
                result[row.id] = {
                    "provides": [p.capability for p in manifest.provides],
                    "url": url,
                    "secrets": secrets,
                }
        return result

    def plan_install(
        self,
        wanted: Sequence[str],
        choices: Mapping[str, str] | None = None,
        *,
        replace: bool = False,
    ) -> Plan:
        with self._sessions() as session:
            explicit, stored = self._state(session)
        plan = plan_install(
            self._manifests(), explicit, wanted, {**stored, **(choices or {})}, replace=replace
        )
        return self._effective(plan)

    def plan_uninstall(self, removed: Sequence[str], *, confirm_cascade: bool = False) -> Plan:
        with self._sessions() as session:
            explicit, stored = self._state(session)
        plan = plan_uninstall(
            self._manifests(), explicit, removed, stored, confirm_cascade=confirm_cascade
        )
        return self._effective(plan)

    def _effective(self, plan: Plan) -> Plan:
        """The steps that bring what is *really* running to the plan's target.

        The SDK plans from the explicit set; after a crash or a failed rollback a dependency can
        be running with nothing left that needs it. Planning against reality installs only what
        is missing and removes such orphans.
        """
        with self._sessions() as session:
            running = frozenset(session.scalars(select(Module.id).where(Module.state == "running")))
        manifests = self._manifests()
        to_remove = running - plan.installed
        known = {m for m in to_remove if m in manifests}
        removal_order = list(reversed(install_order(manifests, known)))
        removal_order += sorted(to_remove - known)  # modules the catalogue no longer knows
        to_add = plan.installed - running
        steps = tuple(
            [Step("uninstall", m) for m in removal_order]
            + [Step("install", m) for m in install_order(manifests, to_add)]
        )
        return replace(plan, steps=steps)

    # --- operations ----------------------------------------------------------------------------

    def install(
        self,
        wanted: Sequence[str],
        choices: Mapping[str, str] | None = None,
        *,
        replace: bool = False,
    ) -> Plan:
        with self._lock:
            plan = self.plan_install(wanted, choices, replace=replace)
            self._execute(plan)
            return plan

    def uninstall(self, removed: Sequence[str], *, confirm_cascade: bool = False) -> Plan:
        with self._lock:
            plan = self.plan_uninstall(removed, confirm_cascade=confirm_cascade)
            self._execute(plan)
            return plan

    def _execute(self, plan: Plan) -> None:
        done: list[tuple[str, str]] = []  # (action, module)
        current = ("", "")
        try:
            for step in plan.steps:
                current = (step.action, step.module)
                if step.action == "uninstall":
                    self._uninstall_module(step.module)
                else:
                    self._install_module(step.module)
                done.append(current)
            self._apply_explicit(plan.explicit)
        except _StepFailed as failure:
            rolled = self._rollback(done, failing=current)
            self._sync_edge_quietly()
            raise ModuleOperationFailed(
                failure.module,
                failure.step,
                failure.code,
                rolled_back=rolled,
                partial=any(action == "uninstall" for action, _ in done),
            ) from None
        self._sync_edge_quietly()  # removals leave their route behind otherwise

    def _sync_edge(self) -> None:
        """Publish the routes of the modules that run (and only those)."""
        manifests = self._manifests()
        with self._sessions() as session:
            running = sorted(session.scalars(select(Module.id).where(Module.state == "running")))
        routes: dict[str, str] = {}
        for module_id in running:
            manifest = manifests.get(module_id)
            text = render_route(manifest) if manifest is not None else None
            if text is not None:
                routes[module_id] = text
        self._edge.sync(routes)

    def _sync_edge_quietly(self) -> None:
        """After a removal or a rollback: a proxy that cannot be updated must not block it."""
        try:
            self._sync_edge()
        except Exception as exc:
            code = exc.code if isinstance(exc, RunnerError) else "internal_error"
            log.warning("could not update the proxy routes: %s", code)
            self._event("platform", "route", "sync", ok=False, code=code)

    def _apply_explicit(self, explicit: frozenset[str]) -> None:
        with self._sessions() as session:
            for row in session.scalars(select(Module).where(Module.state == "running")):
                row.explicit = row.id in explicit
            session.commit()

    # --- one module: install -------------------------------------------------------------------

    def _event(
        self,
        module_id: str,
        kind: str,
        step: str | None = None,
        *,
        ok: bool = True,
        code: str | None = None,
        params: Mapping[str, Any] | None = None,
    ) -> None:
        with self._sessions() as session:
            session.add(
                ModuleEvent(
                    module_id=module_id,
                    kind=kind,
                    step=step,
                    outcome="ok" if ok else "error",
                    code=code,
                    params=dict(params or {}),
                )
            )
            session.commit()
        if self._on_event is not None:
            try:  # progress must never break an operation
                self._on_event(
                    {
                        "module": module_id,
                        "kind": kind,
                        "step": step,
                        "ok": ok,
                        "code": code,
                    }
                )
            except Exception:
                log.warning("module event sink failed", exc_info=True)

    def _step(self, module_id: str, kind: str, name: str, action: Callable[[], None]) -> None:
        try:
            action()
        except _StepFailed:
            raise
        except Exception as exc:  # BaseException (a crash) must pass through untouched
            code = _code_of(exc)
            if code == "internal_error":
                log.error("module %s step %s failed: %s", module_id, name, type(exc).__name__)
            self._event(module_id, kind, name, ok=False, code=code)
            raise _StepFailed(module_id, name, code) from None
        self._event(module_id, kind, name)

    @staticmethod
    def _require(session: Session, module_id: str) -> Module:
        row = session.get(Module, module_id)
        if row is None:
            raise RunnerError("module_missing")  # removed under our feet: abort the step
        return row

    def _bump_generation(self, session: Session) -> None:
        state = session.get(PlatformState, 1)
        if state is None:
            state = PlatformState(id=1)
            session.add(state)
            session.flush()
        state.modules_generation += 1

    def _secret_env(self, module_id: str) -> dict[str, str]:
        env = {**self._platform_env, "COBBLE_MODULE_ID": module_id}
        with self._sessions() as session:
            for key in self._store.keys(session, module_id):
                value = self._store.get(session, module_id, key)
                if value is not None:
                    env[f"COBBLE_SECRET_{key.upper()}"] = value.reveal()
        return env

    def _run_hook(
        self, module_id: str, script: str, extra: Mapping[str, str] | None = None
    ) -> None:
        manifest = self._manifests().get(module_id)
        peers = self._required_peers(manifest) if manifest is not None else {}
        env = {**self._secret_env(module_id), **peers, **(extra or {})}
        result: HookResult = self._runner.run_hook(
            f"{self._catalog.module_dir(module_id)}/{script}", env
        )
        if result.returncode != 0:
            raise RunnerError("hook_failed")
        with self._sessions() as session:
            for key, value in result.produced_secrets.items():
                self._store.set(session, module_id, key, SecretValue(value))
            session.commit()

    def _install_module(self, module_id: str) -> None:
        manifest = self._manifests()[module_id]
        project = _project(module_id)
        variant_id: list[str | None] = [None]
        compose: list[dict[str, Any]] = []

        def record() -> None:
            with self._sessions() as session:
                session.add(Module(id=module_id, version=manifest.version, state="installing"))
                session.commit()

        def hardware() -> None:
            variant = choose_variant(manifest, self._hardware)
            variant_id[0] = variant.id if variant else None
            with self._sessions() as session:
                row = self._require(session, module_id)
                row.variant = variant_id[0]
                session.commit()

        def secrets() -> None:
            with self._sessions() as session:
                for key in manifest.secrets:
                    self._store.generate(session, module_id, key)
                session.commit()

        def pre_up() -> None:
            if not manifest.hooks.pre_up:
                return
            self._run_hook(module_id, manifest.hooks.pre_up)

        def render() -> None:
            raw = self._catalog.compose(module_id, variant_id[0], self._secret_env(module_id))
            result = rewrite_compose(
                raw,
                manifest,
                module_dir=self._catalog.module_dir(module_id),
                bus_network=self._bus_network,
            )
            compose.append(result.compose)

        def up() -> None:
            self._runner.up(project, compose[0], self._secret_env(module_id))

        def post_install() -> None:
            if manifest.hooks.post_install:
                self._run_hook(module_id, manifest.hooks.post_install)

        def register_core() -> None:
            if manifest.hooks.register_core:
                self._run_hook(module_id, manifest.hooks.register_core)

        def health() -> None:
            if not self._runner.wait_healthy(project, self._health_timeout_s):
                raise RunnerError("unhealthy")
            with self._sessions() as session:
                row = self._require(session, module_id)
                row.state = "running"
                self._bump_generation(session)
                session.commit()

        def route() -> None:
            self._sync_edge()

        def link() -> None:
            self._link_new(module_id)

        self._start(module_id)
        for name, action in (
            ("record", record),
            ("hardware", hardware),
            ("secrets", secrets),
            ("pre_up", pre_up),
            ("render", render),
            ("up", up),
            ("post_install", post_install),
            ("register_core", register_core),
            ("health", health),
            ("route", route),
            ("link", link),
        ):
            self._step(module_id, "install", name, action)

    def _start(self, module_id: str) -> None:
        """A leftover row of an earlier failed attempt is cleaned before a new attempt."""
        with self._sessions() as session:
            row = session.get(Module, module_id)
            leftover = row is not None and row.state != "running"
        if leftover:
            self._teardown(module_id, kind="cleanup")

    # --- links ---------------------------------------------------------------------------------

    def _link_new(self, module_id: str) -> None:
        manifests = self._manifests()
        with self._sessions() as session:
            running = set(session.scalars(select(Module.id).where(Module.state == "running")))
            stored = {
                (link.consumer, link.provider, link.capability)
                for link in session.scalars(select(ModuleLink))
            }
        wanted = desired_links(manifests, running | {module_id})
        involved = [item for item in wanted if module_id in (item.consumer, item.provider)]
        for link in sorted(involved, key=lambda i: (i.provider, i.consumer, i.capability)):
            if (link.consumer, link.provider, link.capability) in stored:
                continue
            self._link_hooks(link.consumer, link.provider, link.capability, "on_link")
            with self._sessions() as session:
                session.add(
                    ModuleLink(
                        consumer=link.consumer,
                        provider=link.provider,
                        capability=link.capability,
                        state="linked",
                    )
                )
                session.commit()

    def _required_peers(self, manifest: Manifest) -> dict[str, str]:
        """`COBBLE_PEER_<CAPABILITY>_*` for the running module that provides each capability the
        module requires (the first by id when there are several)."""
        manifests = self._manifests()
        with self._sessions() as session:
            running = set(session.scalars(select(Module.id).where(Module.state == "running")))
        env: dict[str, str] = {}
        for capability in manifest.requires:
            providers = sorted(
                m
                for m in running
                if m in manifests and any(p.capability == capability for p in manifests[m].provides)
            )
            if providers:
                prefix = f"COBBLE_PEER_{capability.upper().replace('-', '_')}_"
                env.update(self._peer_env(providers[0], prefix))
        return env

    def _peer_env(self, peer_id: str, prefix: str) -> dict[str, str]:
        """How a hook reaches a peer: its address and the secrets it shares with linked modules
        (`link_secrets`), and nothing else."""
        manifest = self._manifests().get(peer_id)
        if manifest is None:
            return {}
        env = {f"{prefix}MODULE": peer_id}
        if manifest.web_ui is not None:
            env[f"{prefix}HOST"] = f"cobble-{peer_id}-{manifest.web_ui.service}"
            env[f"{prefix}PORT"] = str(manifest.web_ui.port)
        with self._sessions() as session:
            for key in manifest.link_secrets:
                value = self._store.get(session, peer_id, key)
                if value is not None:
                    env[f"{prefix}SECRET_{key.upper()}"] = value.reveal()
        return env

    def _link_hooks(
        self, consumer: str, provider: str, capability: str, which: str, *, strict: bool = True
    ) -> None:
        manifests = self._manifests()
        for role, module_id, peer in (
            ("provider", provider, consumer),
            ("consumer", consumer, provider),
        ):
            hooks = getattr(manifests[module_id].hooks, which)
            script = hooks.get(capability)
            if not script:
                continue
            extra = {
                "COBBLE_LINK_ROLE": role,
                "COBBLE_LINK_PEER": peer,
                "COBBLE_LINK_CAPABILITY": capability,
            }
            extra.update(self._peer_env(peer, "COBBLE_PEER_"))
            try:
                self._run_hook(module_id, script, extra)
            except RunnerError as exc:
                self._event(
                    module_id, "link" if which == "on_link" else "unlink", ok=False, code=exc.code
                )
                if strict:
                    raise _StepFailed(module_id, which, exc.code) from None
                continue
            self._event(module_id, "link" if which == "on_link" else "unlink", capability)

    # --- one module: uninstall -----------------------------------------------------------------

    def _uninstall_module(self, module_id: str) -> None:
        with self._sessions() as session:
            row = session.get(Module, module_id)
            if row is not None:
                row.state = "removing"
                session.commit()
        self._teardown(module_id, kind="uninstall")

    def _teardown(self, module_id: str, *, kind: str) -> None:
        """Unlink, stop, delete. Hook failures never block a removal; a failed `down` does."""
        manifest = self._manifests().get(module_id)
        with self._sessions() as session:
            links = [
                (link.consumer, link.provider, link.capability)
                for link in session.scalars(
                    select(ModuleLink).where(
                        (ModuleLink.consumer == module_id) | (ModuleLink.provider == module_id)
                    )
                )
            ]
        if manifest is not None:
            for consumer, provider, capability in links:
                self._link_hooks(consumer, provider, capability, "on_unlink", strict=False)
            if manifest.hooks.pre_uninstall:
                try:
                    self._run_hook(module_id, manifest.hooks.pre_uninstall)
                except RunnerError as exc:
                    self._event(module_id, kind, "pre_uninstall", ok=False, code=exc.code)
        try:
            self._runner.down(_project(module_id), volumes=True)
        except RunnerError as exc:
            with self._sessions() as session:
                row = session.get(Module, module_id)
                if row is not None:
                    row.state = "failed"
                    row.last_error = "down_failed"
                    session.commit()
            self._event(module_id, kind, "down", ok=False, code=exc.code)
            raise _StepFailed(module_id, "down", exc.code) from None
        with self._sessions() as session:
            for link_row in session.scalars(
                select(ModuleLink).where(
                    (ModuleLink.consumer == module_id) | (ModuleLink.provider == module_id)
                )
            ):
                session.delete(link_row)
            self._store.delete_all(session, module_id)
            row = session.get(Module, module_id)
            if row is not None:
                session.delete(row)
            self._bump_generation(session)
            session.commit()
        self._event(module_id, kind, "forget")

    # --- rollback and recovery -----------------------------------------------------------------

    def _rollback(self, done: Sequence[tuple[str, str]], *, failing: tuple[str, str]) -> list[str]:
        """Undo, newest first, the installs of this plan, including the one that failed."""
        undo: list[str] = []
        if failing[0] == "install":
            undo.append(failing[1])
        undo += [module for action, module in reversed(done) if action == "install"]
        rolled: list[str] = []
        for module_id in undo:
            try:
                self._teardown(module_id, kind="rollback")
                rolled.append(module_id)
            except _StepFailed:
                log.error("rollback of %s failed; the module is marked failed", module_id)
        return rolled

    def recover(self) -> list[str]:
        """After a crash: clean up modules left installing or failed, finish those left removing."""
        with self._lock:
            with self._sessions() as session:
                stuck = [
                    (row.id, row.state)
                    for row in session.scalars(
                        select(Module).where(Module.state.in_(("installing", "removing", "failed")))
                    )
                ]
            recovered: list[str] = []
            for module_id, state in stuck:
                try:
                    self._teardown(
                        module_id, kind="recover" if state == "installing" else "uninstall"
                    )
                    recovered.append(module_id)
                except _StepFailed:
                    log.error("recovery of %s failed; the module is marked failed", module_id)
            self._sync_edge_quietly()
            return recovered
