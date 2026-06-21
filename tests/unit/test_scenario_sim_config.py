"""Unit tests for `_resolve_scenario_config`: scenario name -> declared
(vision, overlay) sim config, with a clear fallback for unknown names."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tasks import _resolve_scenario_config


def test_01_arm_takeoff_resolves_to_hover_overlay():
    cfg = _resolve_scenario_config("01_arm_takeoff")
    assert cfg is not None
    assert cfg["scenario"] == "01_arm_takeoff"
    assert cfg["overlay"] == "hover"
    assert cfg["vision"] == "none"


def test_unknown_scenario_has_no_declared_config():
    assert _resolve_scenario_config("99_does_not_exist") is None
