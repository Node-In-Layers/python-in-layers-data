"""Behave environment configuration and hooks."""

from __future__ import annotations

import sys
from pathlib import Path

# Add features directory to path for imports
features_dir = Path(__file__).parent
if str(features_dir) not in sys.path:
    sys.path.insert(0, str(features_dir))

# Import after path is set up
from steps.steps import _cleanout_database


def before_scenario(context, scenario):
    """Run before each scenario."""
    _cleanout_database(context)
    # Setup will be done in the "an orm is setup" step


def after_scenario(context, scenario):
    """Run after each scenario."""
    if hasattr(context, "backend"):
        context.backend.dispose()
    _cleanout_database(context)
