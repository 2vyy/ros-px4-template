"""Unit tests for mission_profile."""

from __future__ import annotations

from ros_px4_template_core.lib.mission_profile import MissionProfileParams, build_mission_profile
from ros_px4_template_core.lib.waypoint_mission import EnuPoint


def test_profile_builds_mission() -> None:
    wps = (EnuPoint(0, 0, 3),)
    m = build_mission_profile(wps, MissionProfileParams())
    assert m.waypoints == wps
    assert m.defaults.tolerance_m == 0.4
