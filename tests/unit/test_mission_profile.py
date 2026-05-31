"""Unit tests for mission_profile."""

from __future__ import annotations

from ros_px4_template_core.lib.mission_profile import MissionProfileParams, build_mission_profile
from ros_px4_template_core.lib.waypoint_mission import EnuPoint


def test_profile_builds_waypoints() -> None:
    wps = (EnuPoint(0, 0, 3),)
    m = build_mission_profile(wps, MissionProfileParams())
    assert m.waypoints == wps
    assert m.marker is None


def test_profile_custom_tolerance() -> None:
    wps = (EnuPoint(1, 2, 3),)
    m = build_mission_profile(wps, MissionProfileParams(tolerance_m=0.8, hold_s=5.0))
    assert m.defaults.tolerance_m == 0.8
    assert m.defaults.hold_s == 5.0
