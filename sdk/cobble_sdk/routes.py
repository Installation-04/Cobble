"""The reverse-proxy route of a module, derived only from validated manifest fields.

Nothing a module author writes freely reaches the proxy configuration: the module id, the
service name, the port and the path are all constrained by the manifest schema, so the text
produced here cannot inject directives.
"""

from __future__ import annotations

from .manifest import Manifest


def upstream(manifest: Manifest) -> str | None:
    """`host:port` of the module's web service on the shared network, or None without web_ui."""
    if manifest.web_ui is None:
        return None
    return f"cobble-{manifest.id}-{manifest.web_ui.service}:{manifest.web_ui.port}"


def llm_endpoint(manifest: Manifest) -> str | None:
    """`http://host:port` of a language-model backend on the shared network, or None."""
    if manifest.llm is None:
        return None
    return f"http://cobble-{manifest.id}-{manifest.llm.service}:{manifest.llm.port}"


def render_route(manifest: Manifest) -> str | None:
    """A Caddy snippet exposing the module under its `web_ui.path` (None unless it is public)."""
    target = upstream(manifest)
    if manifest.web_ui is None or target is None or not manifest.web_ui.public:
        return None
    path = manifest.web_ui.path.rstrip("/")
    if not path:  # the root belongs to the platform's own UI
        return None
    directive = "handle_path" if manifest.web_ui.strip_prefix else "handle"
    return (
        f"# module {manifest.id} (generated, do not edit)\n"
        f"{directive} {path}/* {{\n\treverse_proxy {target}\n}}\n"
    )
