"""Unit tests for waypoint_mission."""

from __future__ import annotations

from pathlib import Path

import pytest
from ros_px4_template_core.lib.mission_profile import (
    MissionProfileParams,
    build_mission_profile,
)
from ros_px4_template_core.lib.waypoint_mission import (
    EnuPoint,
    current_waypoint,
    load_path_yaml,
    reached,
)

DEMO_PATH = Path(__file__).resolve().parents[2] / "config/paths/demo.yaml"


def test_load_path_demo_list() -> None:
    wps = load_path_yaml(DEMO_PATH)
    assert len(wps) == 3
    assert wps[0].z == 3.0


def test_load_path_empty_raises() -> None:
    bad = Path(__file__).resolve().parents[2] / "config/paths/_test_empty.yaml"
    bad.write_text("[]\n")
    try:
        with pytest.raises(ValueError, match="at least one waypoint"):
            load_path_yaml(bad)
    finally:
        bad.unlink(missing_ok=True)


def test_profile_waypoints_match_input() -> None:
    wps = load_path_yaml(DEMO_PATH)
    mission = build_mission_profile(wps, MissionProfileParams())
    assert mission.waypoints == wps


def test_reached_within_tolerance() -> None:
    target = EnuPoint(1.0, 0.0, 3.0)
    assert reached((1.2, 0.1, 3.1), target, 0.4)
    assert not reached((2.0, 0.0, 3.0), target, 0.4)


def test_load_path_nan_raises() -> None:
    bad = Path(__file__).resolve().parents[2] / "config/paths/_test_nan.yaml"
    bad.write_text("- {x: 1.0, y: 0.0, z: .nan}\n")
    try:
        with pytest.raises(ValueError, match="finite"):
            load_path_yaml(bad)
    finally:
        bad.unlink(missing_ok=True)


def test_load_path_inf_raises() -> None:
    bad = Path(__file__).resolve().parents[2] / "config/paths/_test_inf.yaml"
    bad.write_text("- {x: 1.0, y: .inf, z: 2.0}\n")
    try:
        with pytest.raises(ValueError, match="finite"):
            load_path_yaml(bad)
    finally:
        bad.unlink(missing_ok=True)


def test_current_waypoint_bounds() -> None:
    mission = build_mission_profile(
        load_path_yaml(DEMO_PATH),
        MissionProfileParams(),
    )
    assert current_waypoint(mission, 0) == mission.waypoints[0]
    assert current_waypoint(mission, 99) is None


def test_reached_z_tolerance_separates_axes() -> None:
    target = EnuPoint(0.0, 0.0, 3.0)
    # 0.1 m XY from target, 0.5 m above — fails with strict z_tolerance_m=0.4
    assert not reached((0.1, 0.0, 3.5), target, 0.4, z_tolerance_m=0.4)


def test_reached_z_tolerance_allows_large_z() -> None:
    target = EnuPoint(0.0, 0.0, 3.0)
    # Same point passes when z_tolerance_m is large enough
    assert reached((0.1, 0.0, 3.5), target, 0.4, z_tolerance_m=0.6)


def test_reached_xy_miss_fails_with_z_tolerance() -> None:
    target = EnuPoint(0.0, 0.0, 3.0)
    # 0.5 m off in XY but z is perfect — fails on XY tolerance
    assert not reached((0.5, 0.0, 3.0), target, 0.4, z_tolerance_m=0.4)


def test_reached_none_z_tolerance_uses_3d() -> None:
    target = EnuPoint(0.0, 0.0, 3.0)
    # 0.35 m 3D distance — passes with default 3D mode (None)
    assert reached((0.35, 0.0, 3.0), target, 0.4, z_tolerance_m=None)
    # Same: no keyword at all
    assert reached((0.35, 0.0, 3.0), target, 0.4)
