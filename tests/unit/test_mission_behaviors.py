"""Unit tests for mission behaviors."""

from __future__ import annotations

import math

from ros_px4_template_core.lib import mission as _m  # noqa: F401 (registers)
from ros_px4_template_core.lib.mission.commands import GoTo
from ros_px4_template_core.lib.mission.detection import Detection
from ros_px4_template_core.lib.mission.registry import get_behavior
from ros_px4_template_core.lib.mission.types import Inputs


def _inputs(**kw) -> Inputs:
    base = dict(
        now=0.0, pose_enu=(0.0, 0.0, 0.0), yaw_enu=0.0,
        armed=True, altitude_ok=True, estimate_ok=True,
        detections=(), detection_stability={}, input_ages={"odom": 0.0},
    )
    base.update(kw)
    return Inputs(**base)


def test_hold_latches_entry_point() -> None:
    hold = get_behavior("hold")
    scratch: dict = {}
    r = hold(scratch, _inputs(pose_enu=(1.0, 2.0, 3.0)), {"z": 5.0})
    assert isinstance(r.command, GoTo)
    assert (r.command.x, r.command.y, r.command.z) == (1.0, 2.0, 5.0)
    r2 = hold(scratch, _inputs(pose_enu=(9.0, 9.0, 5.0)), {"z": 5.0})
    assert (r2.command.x, r2.command.y, r2.command.z) == (1.0, 2.0, 5.0)


def test_follow_waypoints_advances_after_dwell() -> None:
    fw = get_behavior("follow_waypoints")
    scratch: dict = {}
    params = {"waypoints": [(0.0, 0.0, 3.0), (5.0, 0.0, 3.0)], "hold_s": 2.0, "tolerance_m": 0.4}
    r = fw(scratch, _inputs(now=0.0, pose_enu=(0.0, 0.0, 0.0)), params)
    assert (r.command.x, r.command.y) == (0.0, 0.0)
    assert r.signals["reached"] is False
    fw(scratch, _inputs(now=1.0, pose_enu=(0.0, 0.0, 3.0)), params)
    r = fw(scratch, _inputs(now=3.5, pose_enu=(0.0, 0.0, 3.0)), params)
    assert (r.command.x, r.command.y) == (5.0, 0.0)
    assert r.signals["waypoint_index"] == 1
    fw(scratch, _inputs(now=4.0, pose_enu=(5.0, 0.0, 3.0)), params)
    r = fw(scratch, _inputs(now=6.5, pose_enu=(5.0, 0.0, 3.0)), params)
    assert r.signals["waypoints_done"] is True


def test_center_on_marker_targets_pose_plus_offset() -> None:
    cm = get_behavior("center_on_marker")
    scratch: dict = {}
    det = Detection(id=0, offset_body_flu=(8.0, 0.0, -3.0), stamp=0.0)
    r = cm(
        scratch,
        _inputs(pose_enu=(0.0, 0.0, 3.0), detections=(det,)),
        {"target_id": 0, "altitude_m": 3.0, "hold_s": 10.0},
    )
    assert math.isclose(r.command.x, 8.0, abs_tol=1e-6)
    assert math.isclose(r.command.y, 0.0, abs_tol=1e-6)
    assert math.isclose(r.command.z, 3.0, abs_tol=1e-6)
    assert r.signals["centered"] is False


def test_center_on_marker_hold_complete_after_dwell() -> None:
    cm = get_behavior("center_on_marker")
    scratch: dict = {}
    det = Detection(id=0, offset_body_flu=(0.0, 0.0, -3.0), stamp=0.0)
    params = {"target_id": 0, "altitude_m": 3.0, "hold_s": 5.0, "tolerance_m": 0.4}
    cm(scratch, _inputs(now=0.0, pose_enu=(0.0, 0.0, 3.0), detections=(det,)), params)
    r = cm(scratch, _inputs(now=6.0, pose_enu=(0.0, 0.0, 3.0), detections=(det,)), params)
    assert r.signals["hold_complete"] is True


def test_goto_origin_commands_origin() -> None:
    go = get_behavior("goto_origin")
    r = go({}, _inputs(pose_enu=(5.0, 5.0, 3.0)), {"z": 3.0})
    assert (r.command.x, r.command.y, r.command.z) == (0.0, 0.0, 3.0)


def test_search_lawnmower_steps_through_legs_then_complete() -> None:
    sl = get_behavior("search_lawnmower")
    scratch: dict = {}
    params = {
        "spacing_m": 2.0, "legs": 2, "altitude_m": 3.0, "tolerance_m": 0.5, "center": (0.0, 0.0)
    }
    r = sl(scratch, _inputs(now=0.0, pose_enu=(0.0, 0.0, 3.0)), params)
    assert isinstance(r.command, GoTo)
    assert r.signals["search_complete"] is False
    for _ in range(200):
        tgt = (r.command.x, r.command.y, r.command.z)
        r = sl(scratch, _inputs(now=999.0, pose_enu=tgt), params)
        if r.signals["search_complete"]:
            break
    assert r.signals["search_complete"] is True
