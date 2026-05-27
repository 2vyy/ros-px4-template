"""Pytest path setup for core.lib imports."""

import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / "src" / "ros_px4_template_core"))
sys.path.insert(0, str(root / "tools"))
