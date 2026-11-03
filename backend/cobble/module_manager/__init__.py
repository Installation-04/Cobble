"""The module-manager: the only part of Cobble that will touch Docker (ADR 0008).

It runs as its own container from the backend image, with the vault's master key and (later) the
Docker socket. The API and the worker never get either.
"""
