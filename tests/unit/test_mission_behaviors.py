"""Unit tests for mission behaviors."""

from __future__ import annotations

import math

from ros_px4_template_core.lib import mission as _m  # noqa: F401 (registers)
from ros_px4_template_core.lib.mission.commands import GoTo, Land
from ros_px4_template_core.lib.mission.detection import Detection
from ros_px4_template_core.lib.mission.registry import get_behavior
from ros_px4_template_core.lib.mission.types import Inputs


def _inputs(
    *,
    now: float = 0.0,
    pose_enu: tuple[float, float, float] = (0.0, 0.0, 0.0),
    yaw_enu: float = 0.0,
    armed: bool = True,
    altitude_ok: bool = True,
    estimate_ok: bool = True,
    detections: tuple[Detection, ...] = (),
    detection_stability: dict[int, int] | None = None,
    input_ages: dict[str, float] | None = None,
) -> Inputs:
    return Inputs(
        now=now,
        pose_enu=pose_enu,
        yaw_enu=yaw_enu,
        armed=armed,
        altitude_ok=altitude_ok,
        estimate_ok=estimate_ok,
        detections=detections,
        detection_stability={} if detection_stability is None else detection_stability,
        input_ages={"odom": 0.0} if input_ages is None else input_ages,
    )


def test_hold_latches_entry_point() -> None:
    hold = get_behavior("hold")
    scratch: dict = {}
    r = hold(scratch, _inputs(pose_enu=(1.0, 2.0, 3.0)), {"z": 5.0})
    assert isinstance(r.command, GoTo)
    assert (r.command.x, r.command.y, r.command.z) == (1.0, 2.0, 5.0)
    assert r.command.yaw is None
    r2 = hold(scratch, _inputs(pose_enu=(9.0, 9.0, 5.0)), {"z": 5.0})
    assert isinstance(r2.command, GoTo)
    assert (r2.command.x, r2.command.y, r2.command.z) == (1.0, 2.0, 5.0)


def test_hold_latches_yaw_deg_as_enu_radians() -> None:
    hold = get_behavior("hold")
    scratch: dict = {}
    r = hold(scratch, _inputs(pose_enu=(1.0, 2.0, 3.0)), {"z": 5.0, "yaw_deg": 90.0})
    assert isinstance(r.command, GoTo)
    assert r.command.yaw is not None
    assert math.isclose(r.command.yaw, math.pi / 2, abs_tol=1e-9)
    # Yaw stays latched even if a later tick's params change (entry-point semantics).
    r2 = hold(scratch, _inputs(pose_enu=(1.0, 2.0, 3.0)), {"z": 5.0, "yaw_deg": 0.0})
    assert isinstance(r2.command, GoTo)
    assert r2.command.yaw is not None
    assert math.isclose(r2.command.yaw, math.pi / 2, abs_tol=1e-9)


def test_hold_without_yaw_deg_omits_yaw() -> None:
    hold = get_behavior("hold")
    scratch: dict = {}
    r = hold(scratch, _inputs(pose_enu=(1.0, 2.0, 3.0)), {"z": 5.0})
    assert isinstance(r.command, GoTo)
    assert r.command.yaw is None


def test_follow_waypoints_advances_after_dwell() -> None:
    fw = get_behavior("follow_waypoints")
    scratch: dict = {}
    params = {"waypoints": [(0.0, 0.0, 3.0), (5.0, 0.0, 3.0)], "hold_s": 2.0, "tolerance_m": 0.4}
    r = fw(scratch, _inputs(now=0.0, pose_enu=(0.0, 0.0, 0.0)), params)
    assert isinstance(r.command, GoTo)
    assert (r.command.x, r.command.y) == (0.0, 0.0)
    assert r.signals["reached"] is False
    fw(scratch, _inputs(now=1.0, pose_enu=(0.0, 0.0, 3.0)), params)
    r = fw(scratch, _inputs(now=3.5, pose_enu=(0.0, 0.0, 3.0)), params)
    assert isinstance(r.command, GoTo)
    assert (r.command.x, r.command.y) == (5.0, 0.0)
    assert r.signals["waypoint_index"] == 1
    fw(scratch, _inputs(now=4.0, pose_enu=(5.0, 0.0, 3.0)), params)
    r = fw(scratch, _inputs(now=6.5, pose_enu=(5.0, 0.0, 3.0)), params)
    assert r.signals["waypoints_done"] is True


def test_follow_waypoints_mixed_yaw_advances_with_matching_yaw() -> None:
    fw = get_behavior("follow_waypoints")
    scratch: dict = {}
    params = {
        "waypoints": [(0.0, 0.0, 3.0, 90.0), (5.0, 0.0, 3.0)],
        "hold_s": 2.0,
        "tolerance_m": 0.4,
    }
    r = fw(scratch, _inputs(now=0.0, pose_enu=(0.0, 0.0, 0.0)), params)
    assert isinstance(r.command, GoTo)
    assert (r.command.x, r.command.y) == (0.0, 0.0)
    assert r.command.yaw is not None
    assert math.isclose(r.command.yaw, math.pi / 2, abs_tol=1e-9)

    fw(scratch, _inputs(now=1.0, pose_enu=(0.0, 0.0, 3.0)), params)
    r = fw(scratch, _inputs(now=3.5, pose_enu=(0.0, 0.0, 3.0)), params)
    assert isinstance(r.command, GoTo)
    assert (r.command.x, r.command.y) == (5.0, 0.0)
    assert r.command.yaw is None


def test_follow_waypoints_rejects_malformed_entry_length() -> None:
    fw = get_behavior("follow_waypoints")
    scratch: dict = {}
    params = {"waypoints": [(0.0, 0.0)]}
    try:
        fw(scratch, _inputs(pose_enu=(0.0, 0.0, 0.0)), params)
    except ValueError as exc:
        msg = str(exc)
        assert "0" in msg  # entry index
        assert "3" in msg  # expected length
        assert "4" in msg  # expected length
    else:
        raise AssertionError("expected ValueError for malformed waypoint entry")


def test_center_on_marker_targets_pose_plus_offset() -> None:
    cm = get_behavior("center_on_marker")
    scratch: dict = {}
    det = Detection(id=0, offset_body_flu=(8.0, 0.0, -3.0), stamp=0.0)
    r = cm(
        scratch,
        _inputs(pose_enu=(0.0, 0.0, 3.0), detections=(det,)),
        {"target_id": 0, "altitude_m": 3.0, "hold_s": 10.0},
    )
    assert isinstance(r.command, GoTo)
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
    assert isinstance(r.command, GoTo)
    assert (r.command.x, r.command.y, r.command.z) == (0.0, 0.0, 3.0)


def _cl_params(**overrides: object) -> dict:
    defaults: dict = {
        "target_id": 0,
        "tolerance_m": 0.3,
        "descent_rate_m_s": 0.4,
        "land_altitude_m": 0.7,
        "min_altitude_m": 0.3,
        "marker_fresh_s": 1.0,
        "max_dt_s": 0.5,
    }
    return {**defaults, **overrides}


def test_center_land_descends_while_centered_and_fresh() -> None:
    cl = get_behavior("center_land")
    scratch: dict = {}
    params = _cl_params()
    det0 = Detection(id=0, offset_body_flu=(0.0, 0.0, -3.0), stamp=0.0)
    r0 = cl(scratch, _inputs(now=0.0, pose_enu=(0.0, 0.0, 3.0), detections=(det0,)), params)
    assert isinstance(r0.command, GoTo)
    z0 = r0.command.z
    det1 = Detection(id=0, offset_body_flu=(0.0, 0.0, -3.0), stamp=0.1)
    r1 = cl(scratch, _inputs(now=0.1, pose_enu=(0.0, 0.0, 3.0), detections=(det1,)), params)
    assert isinstance(r1.command, GoTo)
    assert r1.command.z < z0
    assert math.isclose(z0 - r1.command.z, 0.4 * 0.1, abs_tol=1e-6)
    assert r1.signals["centered"] is True
    assert r1.signals["marker_lost"] is False


def test_center_land_holds_altitude_when_not_centered() -> None:
    cl = get_behavior("center_land")
    scratch: dict = {}
    params = _cl_params()
    det0 = Detection(id=0, offset_body_flu=(5.0, 0.0, -3.0), stamp=0.0)
    r0 = cl(scratch, _inputs(now=0.0, pose_enu=(0.0, 0.0, 3.0), detections=(det0,)), params)
    assert r0.signals["centered"] is False
    assert isinstance(r0.command, GoTo)
    z0 = r0.command.z
    det1 = Detection(id=0, offset_body_flu=(5.0, 0.0, -3.0), stamp=1.0)
    r1 = cl(scratch, _inputs(now=1.0, pose_enu=(0.0, 0.0, 3.0), detections=(det1,)), params)
    assert r1.signals["centered"] is False
    assert isinstance(r1.command, GoTo)
    assert math.isclose(r1.command.z, z0, abs_tol=1e-9)


def test_center_land_commands_land_when_low_and_centered() -> None:
    cl = get_behavior("center_land")
    scratch: dict = {}
    params = _cl_params()
    det = Detection(id=0, offset_body_flu=(0.0, 0.0, -0.6), stamp=0.0)
    r = cl(scratch, _inputs(now=0.0, pose_enu=(0.0, 0.0, 0.6), detections=(det,)), params)
    assert isinstance(r.command, Land)
    assert r.signals["land_commanded"] is True
    assert r.signals["centered"] is True


def test_center_land_freezes_altitude_on_marker_loss() -> None:
    cl = get_behavior("center_land")
    scratch: dict = {}
    params = _cl_params(marker_fresh_s=0.05)
    det0 = Detection(id=0, offset_body_flu=(0.0, 0.0, -3.0), stamp=0.0)
    cl(scratch, _inputs(now=0.0, pose_enu=(0.0, 0.0, 3.0), detections=(det0,)), params)
    det1 = Detection(id=0, offset_body_flu=(0.0, 0.0, -3.0), stamp=0.1)
    r1 = cl(scratch, _inputs(now=0.1, pose_enu=(0.0, 0.0, 3.0), detections=(det1,)), params)
    assert isinstance(r1.command, GoTo)
    z_before_loss = r1.command.z
    # Marker disappears entirely; last tx/ty is retained but altitude must freeze.
    r2 = cl(scratch, _inputs(now=0.2, pose_enu=(0.0, 0.0, 3.0), detections=()), params)
    assert isinstance(r2.command, GoTo)
    assert math.isclose(r2.command.z, z_before_loss, abs_tol=1e-9)
    assert (r2.command.x, r2.command.y) == (0.0, 0.0)
    assert r2.signals["marker_lost"] is True
    r3 = cl(scratch, _inputs(now=0.3, pose_enu=(0.0, 0.0, 3.0), detections=()), params)
    assert isinstance(r3.command, GoTo)
    assert math.isclose(r3.command.z, z_before_loss, abs_tol=1e-9)
    assert r3.signals["marker_lost"] is True


def test_center_land_dt_clamp_rejects_negative_delta() -> None:
    cl = get_behavior("center_land")
    scratch: dict = {}
    params = _cl_params()
    det0 = Detection(id=0, offset_body_flu=(0.0, 0.0, -3.0), stamp=5.0)
    r0 = cl(scratch, _inputs(now=5.0, pose_enu=(0.0, 0.0, 3.0), detections=(det0,)), params)
    assert isinstance(r0.command, GoTo)
    z0 = r0.command.z
    # Clock rewinds (now < last_now): dt must clamp to 0, not increase descent.
    det1 = Detection(id=0, offset_body_flu=(0.0, 0.0, -3.0), stamp=4.0)
    r1 = cl(scratch, _inputs(now=4.0, pose_enu=(0.0, 0.0, 3.0), detections=(det1,)), params)
    assert isinstance(r1.command, GoTo)
    assert math.isclose(r1.command.z, z0, abs_tol=1e-9)


def test_center_land_dt_clamp_caps_large_delta() -> None:
    cl = get_behavior("center_land")
    scratch: dict = {}
    params = _cl_params(max_dt_s=0.5)
    det0 = Detection(id=0, offset_body_flu=(0.0, 0.0, -3.0), stamp=0.0)
    r0 = cl(scratch, _inputs(now=0.0, pose_enu=(0.0, 0.0, 3.0), detections=(det0,)), params)
    assert isinstance(r0.command, GoTo)
    z0 = r0.command.z
    # A huge tick gap (e.g. a stall) must not translate into a huge descent step.
    det1 = Detection(id=0, offset_body_flu=(0.0, 0.0, -3.0), stamp=50.0)
    r1 = cl(scratch, _inputs(now=50.0, pose_enu=(0.0, 0.0, 3.0), detections=(det1,)), params)
    assert isinstance(r1.command, GoTo)
    assert math.isclose(z0 - r1.command.z, 0.4 * 0.5, abs_tol=1e-6)


def test_center_land_latches_land_for_the_episode() -> None:
    """After the hand-off, marker loss must NOT signal marker_lost: PX4 owns the
    descent and the marker inevitably leaves view near touchdown. The behavior
    keeps emitting Land until the state is exited (disarm -> done)."""
    cl = get_behavior("center_land")
    scratch: dict = {}
    params = _cl_params()
    det = Detection(id=0, offset_body_flu=(0.0, 0.0, -0.6), stamp=0.0)
    r = cl(scratch, _inputs(now=0.0, pose_enu=(0.0, 0.0, 0.6), detections=(det,)), params)
    assert isinstance(r.command, Land)
    # Marker gone, vehicle below ground-effect view: still Land, no marker_lost.
    r2 = cl(scratch, _inputs(now=5.0, pose_enu=(0.0, 0.0, 0.05), detections=()), params)
    assert isinstance(r2.command, Land)
    assert r2.signals["marker_lost"] is False
    assert r2.signals["land_commanded"] is True


def test_center_land_reentry_reinitializes_from_current_altitude() -> None:
    """Fresh scratch (as after a reacquire -> descend re-entry) must not carry
    over the previous episode's z_cmd; it re-derives from the current pose."""
    cl = get_behavior("center_land")
    params = _cl_params()
    det = Detection(id=0, offset_body_flu=(0.0, 0.0, -1.5), stamp=0.0)
    r = cl({}, _inputs(now=0.0, pose_enu=(0.0, 0.0, 1.5), detections=(det,)), params)
    assert isinstance(r.command, GoTo)
    assert math.isclose(r.command.z, 1.5, abs_tol=1e-9)


def test_search_lawnmower_steps_through_legs_then_complete() -> None:
    sl = get_behavior("search_lawnmower")
    scratch: dict = {}
    params = {
        "spacing_m": 2.0,
        "legs": 2,
        "altitude_m": 3.0,
        "tolerance_m": 0.5,
        "center": (0.0, 0.0),
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
