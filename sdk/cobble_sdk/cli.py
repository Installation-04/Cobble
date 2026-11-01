"""`cobble-sdk init | lint | test`: write, check and try a module before submitting it.

No daemon is needed except for the compose rules in `lint`, which use `docker compose config`
when Docker is installed (and say so when it is not). Exit codes: 0 fine, 1 problems found,
2 usage.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import stat
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from .manifest import MODULE_ID, Manifest, ManifestError, load_manifest
from .resolve import (
    Hardware,
    NeedsChoice,
    NoCompatibleVariant,
    ResolveError,
    choose_variant,
    plan_install,
    plan_uninstall,
)
from .rewrite import ComposeRejected, rewrite_compose

PLACEHOLDER_DIGEST = "0" * 64

MANIFEST_TEMPLATE = """\
# {id}: replace this description. See the manifest reference in the SDK README.
id: {id}
name: {title}
version: 0.1.0
category: other
description:
  en: What {title} does, in one sentence.
  fr: Ce que fait {title}, en une phrase.
license: MIT
provides: []
requires: []
# Pin the image by digest: `docker buildx imagetools inspect <image>:<tag>` prints it.
images:
  - docker.io/library/nginx:1.27-alpine@sha256:{digest}
compose: compose.yml
web_ui:
  service: app
  port: 80
  path: /{id}
healthcheck:
  http: /
"""

COMPOSE_TEMPLATE = """\
# Only declare what the module needs: the platform removes published ports, renames
# everything under `cobble-<id>` and applies CPU, memory and process limits.
services:
  app:
    image: docker.io/library/nginx:1.27-alpine@sha256:{digest}
    restart: unless-stopped
"""


def _say(text: str = "", *, err: bool = False) -> None:
    print(text, file=sys.stderr if err else sys.stdout)


def add_parser(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="cobble-sdk", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init", help="create a module skeleton")
    init.add_argument("id")
    init.add_argument("--dir", default=".", help="where to create <id>/ (default: here)")
    lint = sub.add_parser("lint", help="check modules (a module directory or a catalogue)")
    lint.add_argument("paths", nargs="+")
    lint.add_argument(
        "--no-compose", action="store_true", help="skip the compose rules (no Docker)"
    )
    test = sub.add_parser("test", help="try installing and removing a module on sample machines")
    test.add_argument("module", help="the module directory")
    test.add_argument(
        "--catalog", default=None, help="the catalogue to resolve against (default: its parent)"
    )
    return parser.parse_args(argv)


# --- init --------------------------------------------------------------------------------------


def cmd_init(module_id: str, base: str) -> int:
    if not re.fullmatch(MODULE_ID, module_id):
        _say(f"{module_id!r} is not a valid module id: {MODULE_ID}", err=True)
        return 2
    target = Path(base) / module_id
    if target.exists() and any(target.iterdir()):
        _say(f"{target} already exists and is not empty", err=True)
        return 1
    target.mkdir(parents=True, exist_ok=True)
    (target / "manifest.yaml").write_text(
        MANIFEST_TEMPLATE.format(
            id=module_id, title=module_id.replace("-", " ").title(), digest=PLACEHOLDER_DIGEST
        ),
        "utf-8",
    )
    (target / "compose.yml").write_text(COMPOSE_TEMPLATE.format(digest=PLACEHOLDER_DIGEST), "utf-8")
    _say(f"created {target}: edit it, then run `cobble-sdk lint {target}`")
    return 0


# --- lint --------------------------------------------------------------------------------------


def _module_dirs(path: Path) -> list[Path]:
    if (path / "manifest.yaml").is_file():
        return [path]
    return (
        sorted(p for p in path.iterdir() if (p / "manifest.yaml").is_file())
        if path.is_dir()
        else []
    )


def _files_problems(directory: Path, manifest: Manifest) -> list[str]:
    problems: list[str] = []
    composes = {manifest.compose, *(v.compose for v in manifest.variants if v.compose)}
    for name in sorted(composes):
        if not (directory / name).is_file():
            problems.append(f"{name}: the compose file does not exist")
    hooks = [
        manifest.hooks.pre_up,
        manifest.hooks.post_install,
        manifest.hooks.register_core,
        manifest.hooks.pre_uninstall,
        *manifest.hooks.on_link.values(),
        *manifest.hooks.on_unlink.values(),
    ]
    for hook in sorted({h for h in hooks if h}):
        path = directory / hook
        if not path.is_file():
            problems.append(f"{hook}: the hook does not exist")
        elif not path.stat().st_mode & stat.S_IXUSR:
            problems.append(f"{hook}: the hook is not executable (chmod +x)")
    if manifest.id != directory.resolve().name:
        problems.append(f"id: {manifest.id!r} must match the directory name {directory.name!r}")
    return problems


def _placeholder_problems(directory: Path, manifest: Manifest) -> list[str]:
    problems = [
        f"images: {image} uses the placeholder digest from `init`: pin the real one"
        for image in manifest.images
        if PLACEHOLDER_DIGEST in image
    ]
    compose = directory / manifest.compose
    if compose.is_file() and PLACEHOLDER_DIGEST in compose.read_text("utf-8"):
        problems.append(f"{manifest.compose}: still has the placeholder digest from `init`")
    return problems


def _render(directory: Path, manifest: Manifest, compose_file: str) -> dict[str, Any] | str:
    """The compose file as Docker resolves it, or why that was not possible."""
    docker = shutil.which("docker")
    if docker is None:
        return "docker is not installed"
    env = {k: v for k, v in os.environ.items() if k in ("PATH", "HOME", "DOCKER_HOST")}
    env.update({f"COBBLE_SECRET_{k.upper()}": "lint" for k in manifest.secrets})
    # Any platform variable the file mentions (secrets made by hooks, peers, the public URL...)
    # gets a stand-in value: only the file's structure is checked here, not its runtime values.
    text = (directory / compose_file).read_text("utf-8")
    env.update(dict.fromkeys(re.findall(r"\$\{?(COBBLE_[A-Z0-9_]+)", text), "lint"))
    env.update({"COBBLE_MODULE_ID": manifest.id, "COBBLE_VARIANT": ""})
    result = subprocess.run(  # noqa: S603
        [
            docker,
            "compose",
            "--project-directory",
            str(directory),
            "-f",
            str(directory / compose_file),
            "config",
            "--format",
            "json",
        ],
        capture_output=True,
        text=True,
        env=env,
        check=False,
        timeout=60,
    )
    if result.returncode != 0:
        return result.stderr.strip().splitlines()[-1] if result.stderr.strip() else "config failed"
    loaded = json.loads(result.stdout)
    return loaded if isinstance(loaded, dict) else "unexpected output"


def _compose_problems(directory: Path, manifest: Manifest) -> tuple[list[str], list[str]]:
    """(problems, notes): rule violations are problems; being unable to check is a note."""
    problems: list[str] = []
    notes: list[str] = []
    composes = {manifest.compose, *(v.compose for v in manifest.variants if v.compose)}
    for name in sorted(composes):
        if not (directory / name).is_file():
            continue  # reported by the files check
        rendered = _render(directory, manifest, name)
        if isinstance(rendered, str):
            notes.append(f"{name}: the platform rules were not checked ({rendered})")
            continue
        try:
            rewrite_compose(rendered, manifest, module_dir=str(directory.resolve()))
        except ComposeRejected as exc:
            problems.extend(
                f"{name}: {v.service or '<file>'}: {v.code} ({v.detail})" for v in exc.violations
            )
    return problems, notes


def cmd_lint(paths: Sequence[str], *, compose: bool) -> int:
    directories = [d for p in paths for d in _module_dirs(Path(p))]
    if not directories:
        _say("no module found (a module directory has a manifest.yaml)", err=True)
        return 2
    failed = 0
    for directory in directories:
        try:
            manifest = load_manifest(directory / "manifest.yaml")
        except ManifestError as exc:
            problems, notes = list(exc.problems), list[str]()
        else:
            problems = _files_problems(directory, manifest) + _placeholder_problems(
                directory, manifest
            )
            notes = []
            if compose:
                found, notes = _compose_problems(directory, manifest)
                problems += found
        for note in notes:
            _say(f"{directory.name}: note: {note}")
        if problems:
            failed += 1
            for problem in problems:
                _say(f"{directory.name}: {problem}", err=True)
        else:
            _say(f"{directory.name}: ok")
    return 1 if failed else 0


# --- test --------------------------------------------------------------------------------------

PROFILES: tuple[tuple[str, Hardware], ...] = (
    ("1 GB, no GPU", Hardware(1024, "none")),
    ("4 GB, no GPU", Hardware(4096, "none")),
    ("16 GB, no GPU", Hardware(16384, "none")),
    ("16 GB, NVIDIA", Hardware(16384, "nvidia")),
    ("16 GB, AMD", Hardware(16384, "amd")),
)


def _load_catalog(root: Path, module_dir: Path) -> dict[str, Manifest]:
    catalog: dict[str, Manifest] = {}
    for directory in _module_dirs(root):
        try:
            manifest = load_manifest(directory / "manifest.yaml")
        except ManifestError:
            continue
        catalog[manifest.id] = manifest
    manifest = load_manifest(module_dir / "manifest.yaml")
    catalog[manifest.id] = manifest
    return catalog


def cmd_test(module: str, catalog_dir: str | None) -> int:
    module_dir = Path(module)
    try:
        manifest = load_manifest(module_dir / "manifest.yaml")
    except ManifestError as exc:
        for problem in exc.problems:
            _say(f"{module_dir.name}: {problem}", err=True)
        return 1
    catalog = _load_catalog(
        Path(catalog_dir) if catalog_dir else module_dir.resolve().parent, module_dir
    )
    failures: list[str] = []
    for label, hardware in PROFILES:
        try:
            choose_variant(manifest, hardware)
        except NoCompatibleVariant as exc:
            _say(f"{label}: does not fit ({', '.join(p.code for p in exc.problems)}), as declared")
            continue
        try:
            plan = plan_install(catalog, set(), [manifest.id])
        except NeedsChoice as exc:
            _say(f"{label}: needs a choice for {exc.capability} ({', '.join(exc.candidates)})")
            continue
        except ResolveError as exc:
            failures.append(f"{label}: cannot be installed: {exc}")
            continue
        try:
            back = plan_uninstall(catalog, plan.explicit, [manifest.id], confirm_cascade=True)
        except ResolveError as exc:
            failures.append(f"{label}: cannot be removed: {exc}")
            continue
        if back.installed:
            failures.append(f"{label}: removing it leaves {sorted(back.installed)} installed")
            continue
        _say(f"{label}: installs ({len(plan.steps)} steps) and removes cleanly")
    for failure in failures:
        _say(f"{manifest.id}: {failure}", err=True)
    return 1 if failures else 0


def main(argv: Sequence[str] | None = None) -> int:
    args = add_parser(argv)
    if args.command == "init":
        return cmd_init(args.id, args.dir)
    if args.command == "lint":
        return cmd_lint(args.paths, compose=not args.no_compose)
    return cmd_test(args.module, args.catalog)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
