"""Unit tests for waypoint_mission."""

from __future__ import annotations

from pathlib import Path

from ros_px4_template_core.lib.waypoint_mission import (
    EnuPoint,
    current_waypoint,
    load_mission_yaml,
    reached,
)

MISSION = Path(__file__).resolve().parents[2] / "config/missions/inspect_aruco.yaml"


def test_load_inspect_aruco() -> None:
    m = load_mission_yaml(MISSION)
    assert m.frame_id == "map"
    assert len(m.waypoints) == 3
    assert m.marker is not None
    assert m.marker.hold_offset_enu.z == 1.5


def test_reached_within_tolerance() -> None:
    target = EnuPoint(1.0, 0.0, 3.0)
    assert reached((1.2, 0.1, 3.1), target, 0.4)
    assert not reached((2.0, 0.0, 3.0), target, 0.4)


def test_current_waypoint_bounds() -> None:
    m = load_mission_yaml(MISSION)
    assert current_waypoint(m, 0) == m.waypoints[0]
    assert current_waypoint(m, 99) is None
