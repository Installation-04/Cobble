"""Stateless, signed tokens that a coding agent presents to the internal LLM endpoint.

A token binds one agent run to a project, a task and a role (and optionally a model chosen by
the scheduler after an escalation). It is signed with HMAC-SHA256 and expires, so a leaked token
is useless outside its run. Only the scheduler can issue one (it knows the secret).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import uuid
from dataclasses import dataclass


class InvalidRunToken(Exception):
    pass


@dataclass(frozen=True)
class RunClaims:
    task_id: uuid.UUID
    project_id: uuid.UUID
    role: str
    exp: int
    model_override: str | None = None


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _sign(secret: str, payload: str) -> str:
    return _b64(hmac.new(secret.encode(), payload.encode("ascii"), hashlib.sha256).digest())


def issue(
    secret: str,
    *,
    task_id: uuid.UUID,
    project_id: uuid.UUID,
    role: str,
    ttl_s: int,
    model_override: str | None = None,
    now: float | None = None,
) -> str:
    if not secret:
        raise ValueError("run token secret is not configured")
    exp = int((now if now is not None else time.time()) + ttl_s)
    claims = {
        "t": str(task_id),
        "p": str(project_id),
        "r": role,
        "e": exp,
        "m": model_override,
    }
    payload = _b64(json.dumps(claims, separators=(",", ":"), sort_keys=True).encode())
    return f"{payload}.{_sign(secret, payload)}"


def verify(secret: str, token: str, now: float | None = None) -> RunClaims:
    """Return the claims of a valid, unexpired token or raise InvalidRunToken."""
    if not secret:
        raise InvalidRunToken("run token secret is not configured")
    try:
        payload, signature = token.split(".", 1)
        if not hmac.compare_digest(signature, _sign(secret, payload)):
            raise InvalidRunToken("bad signature")
        raw = json.loads(_unb64(payload))
        claims = RunClaims(
            task_id=uuid.UUID(raw["t"]),
            project_id=uuid.UUID(raw["p"]),
            role=str(raw["r"]),
            exp=int(raw["e"]),
            model_override=raw.get("m"),
        )
    except InvalidRunToken:
        raise
    except (ValueError, KeyError, TypeError) as exc:
        raise InvalidRunToken("malformed token") from exc
    if (now if now is not None else time.time()) >= claims.exp:
        raise InvalidRunToken("expired")
    return claims
