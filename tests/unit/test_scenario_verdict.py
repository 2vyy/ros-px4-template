"""Unit tests for the scenario verdict line emitted by _common.write_report."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tests" / "scenarios"))

from _common import scenario_verdict_line


def test_pass_line_lists_detail() -> None:
    line = scenario_verdict_line("03_waypoint", True, 12.4, {"waypoints_done": 3, "phase": "done"})
    assert line.startswith("PASS 03_waypoint")
    assert "waypoints_done=3" in line
    assert "phase=done" in line
    assert "12.4s" in line


def test_fail_line_leads_with_reason() -> None:
    line = scenario_verdict_line("03_waypoint", False, 61.0, {"reason": "timeout", "phase": "climb"})
    assert line.startswith("FAIL 03_waypoint")
    assert "timeout" in line
    assert "phase=climb" in line


def test_pass_with_empty_detail_says_ok() -> None:
    line = scenario_verdict_line("05_aruco_hover", True, 18.7, {})
    assert line.startswith("PASS 05_aruco_hover")
    assert "ok" in line
