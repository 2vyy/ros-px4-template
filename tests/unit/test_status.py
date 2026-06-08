"""Unit tests for the concise English status snapshot."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

from status import format_status


def test_status_down() -> None:
    text = format_status(
        sim_alive=False, nodes=None, scenarios=[], last_event=None, ros_env_error=None
    )
    assert "stack: down" in text.lower()
    assert "just sim" in text  # hint to start


def test_status_up_lists_nodes_and_scenarios() -> None:
    text = format_status(
        sim_alive=True,
        nodes=["/offboard_controller", "/mission_manager"],
        scenarios=[{"name": "01_arm_takeoff", "passed": True, "elapsed_s": 6.2}],
        last_event={"t": 42.0, "event": "PHASE_CHANGE", "node": "mission_manager"},
        ros_env_error=None,
    )
    assert "stack: up" in text.lower()
    assert "2 nodes" in text
    assert "01_arm_takeoff" in text
    assert "PASS" in text
    assert "PHASE_CHANGE" in text


def test_status_surfaces_ros_env_error() -> None:
    text = format_status(
        sim_alive=False,
        nodes=None,
        scenarios=[],
        last_event=None,
        ros_env_error="ros2 not on PATH",
    )
    assert "ros2 not on PATH" in text
