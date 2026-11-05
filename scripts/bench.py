#!/usr/bin/env python3
"""Agent bench entry point (`make bench`): see docs/en/bench.md and docs/fr/bench.md."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from cobble_bench.cli import main

if __name__ == "__main__":
    sys.exit(main())
