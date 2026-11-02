"""Tiny client of the module-manager service, run INSIDE its container (it has the token):

    docker compose -f core/compose.yml --profile modules exec -T module-manager \
        python - install forgejo < scripts/module_client.py

Actions: install MODULE..., uninstall MODULE..., connections, catalog. Developer tooling for the
smoke test and debugging; the product's own interfaces are the API (Store) and the CLI.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from typing import Any

TOKEN = os.environ["COBBLE_MODULE_MANAGER_TOKEN"]


def call(method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    request = urllib.request.Request(
        "http://localhost:8095" + path,
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": "Bearer " + TOKEN, "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310
            result: dict[str, Any] = json.load(response)
            return result
    except urllib.error.HTTPError as error:
        return {"http": error.code, **json.load(error)}


def main(argv: list[str]) -> None:
    action, *modules = argv
    if action in ("install", "uninstall"):
        started = call("POST", "/v1/operations", {"action": action, "modules": modules})
        print(started)
        if "operation_id" not in started:
            sys.exit(1)
        while True:
            operation = call("GET", "/v1/operations/" + started["operation_id"])
            if operation["state"] != "running":
                print(json.dumps(operation))
                sys.exit(0 if operation["state"] == "done" else 1)
            time.sleep(3)
    elif action == "connections":
        print(json.dumps(call("GET", "/v1/connections")))
    elif action == "catalog":
        listing = call("GET", "/v1/catalog")["modules"]
        print(json.dumps([(m["id"], m["hardware"], m["installed"]) for m in listing]))
    else:
        sys.exit("unknown action")


main(sys.argv[1:])
