"""Pytest configuration and fixtures."""

from __future__ import annotations

import sys
from pathlib import Path

# Add src directory to Python path for tests
# This must happen before any test imports
src_path = Path(__file__).parent.parent / "src"
src_path_str = str(src_path.resolve())
if src_path_str not in sys.path:
    sys.path.insert(0, src_path_str)
