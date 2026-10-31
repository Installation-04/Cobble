from __future__ import annotations

import uuid

import pytest

from cobble.auth import runtoken

SECRET = "unit-test-secret"
TASK, PROJECT = uuid.uuid4(), uuid.uuid4()


def make(**kw: object) -> str:
    args: dict[str, object] = {
        "task_id": TASK,
        "project_id": PROJECT,
        "role": "worker",
        "ttl_s": 60,
        "now": 1000.0,
    }
    args.update(kw)
    return runtoken.issue(SECRET, **args)  # type: ignore[arg-type]


def test_roundtrip() -> None:
    claims = runtoken.verify(SECRET, make(model_override="strong"), now=1010.0)
    assert (claims.task_id, claims.project_id, claims.role) == (TASK, PROJECT, "worker")
    assert claims.model_override == "strong"
    assert claims.exp == 1060


def test_expired_token_is_rejected() -> None:
    with pytest.raises(runtoken.InvalidRunToken):
        runtoken.verify(SECRET, make(), now=1060.0)


def test_wrong_secret_and_tampering_are_rejected() -> None:
    token = make()
    with pytest.raises(runtoken.InvalidRunToken):
        runtoken.verify("other-secret", token, now=1001.0)
    payload, signature = token.split(".")
    forged = runtoken.issue(
        SECRET, task_id=TASK, project_id=uuid.uuid4(), role="worker", ttl_s=60, now=1000.0
    ).split(".")[0]
    with pytest.raises(runtoken.InvalidRunToken):
        runtoken.verify(SECRET, f"{forged}.{signature}", now=1001.0)
    with pytest.raises(runtoken.InvalidRunToken):
        runtoken.verify(SECRET, payload, now=1001.0)  # no signature
    with pytest.raises(runtoken.InvalidRunToken):
        runtoken.verify(SECRET, "not-a-token", now=1001.0)


def test_empty_secret_fails_closed() -> None:
    with pytest.raises(ValueError):
        runtoken.issue("", task_id=TASK, project_id=PROJECT, role="worker", ttl_s=1)
    with pytest.raises(runtoken.InvalidRunToken):
        runtoken.verify("", make(), now=1001.0)
