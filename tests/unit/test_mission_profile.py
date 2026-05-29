"""Unit tests for mission_profile."""

from __future__ import annotations

from ros_px4_template_core.lib.mission_profile import MissionProfileParams, build_mission_profile
from ros_px4_template_core.lib.waypoint_mission import EnuPoint


def test_profile_without_marker() -> None:
    wps = (EnuPoint(0, 0, 3),)
    m = build_mission_profile(wps, MissionProfileParams(enable_marker_hover=False))
    assert m.marker is None


def test_profile_with_marker() -> None:
    wps = (EnuPoint(0, 0, 3),)
    m = build_mission_profile(
        wps,
        MissionProfileParams(enable_marker_hover=True, marker_hold_offset_z=1.5),
    )
    assert m.marker is not None
    assert m.marker.hold_offset_enu.z == 1.5
