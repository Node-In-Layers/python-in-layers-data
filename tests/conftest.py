"""Pytest configuration and fixtures."""

from __future__ import annotations

import sys
from pathlib import Path

# Add local package src directories to Python path for tests.
# This must happen before any test imports so the monorepo sources win over any
# installed package versions in the Poetry environment.
data_src_path = Path(__file__).parent.parent / "src"
core_src_path = Path(__file__).parent.parent.parent / "core" / "src"

for path in [core_src_path, data_src_path]:
    path_str = str(path.resolve())
    if path_str not in sys.path:
        sys.path.insert(0, path_str)
