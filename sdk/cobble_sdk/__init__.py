"""Cobble module SDK (Apache-2.0). It must never import anything from the AGPL `cobble` package."""

from .manifest import Manifest, ManifestError, load_manifest, manifest_json_schema, parse_manifest

__all__ = ["Manifest", "ManifestError", "load_manifest", "manifest_json_schema", "parse_manifest"]
