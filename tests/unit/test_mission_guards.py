"""Unit tests for mission guards."""

from __future__ import annotations

from ros_px4_template_core.lib import mission as _m  # noqa: F401
from ros_px4_template_core.lib.mission.detection import Detection
from ros_px4_template_core.lib.mission.registry import get_guard
from ros_px4_template_core.lib.mission.types import Inputs


def _inputs(
    *,
    now: float = 10.0,
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


def test_armed_at_altitude() -> None:
    g = get_guard("armed_at_altitude")
    assert g(_inputs(armed=True, altitude_ok=True), {}, {}) is True
    assert g(_inputs(armed=False, altitude_ok=True), {}, {}) is False


def test_signal_guards() -> None:
    assert get_guard("waypoints_done")(_inputs(), {"waypoints_done": True}, {}) is True
    assert get_guard("reached")(_inputs(), {"reached": False}, {}) is False
    assert get_guard("hold_complete")(_inputs(), {"hold_complete": True}, {}) is True
    assert get_guard("search_complete")(_inputs(), {"search_complete": True}, {}) is True


def test_marker_fresh_and_stable_and_lost() -> None:
    det = Detection(id=7, offset_body_flu=(0.0, 0.0, -3.0), stamp=9.5)
    ins = _inputs(now=10.0, detections=(det,), detection_stability={7: 6})
    assert get_guard("marker_fresh")(ins, {}, {"id": 7, "t": 1.0}) is True
    assert get_guard("marker_fresh")(ins, {}, {"id": 7, "t": 0.1}) is False
    assert get_guard("marker_stable")(ins, {}, {"id": 7, "n": 5}) is True
    assert get_guard("marker_stable")(ins, {}, {"id": 7, "n": 10}) is False
    old = Detection(id=7, offset_body_flu=(0.0, 0.0, -3.0), stamp=2.0)
    assert (
        get_guard("marker_lost")(_inputs(now=10.0, detections=(old,)), {}, {"id": 7, "t": 3.0})
        is True
    )
    assert get_guard("marker_lost")(ins, {}, {"id": 7, "t": 3.0}) is False


def test_safety_guards() -> None:
    assert (
        get_guard("geofence_breach")(_inputs(pose_enu=(40.0, 30.0, 3.0)), {}, {"radius_m": 50.0})
        is True
    )
    assert (
        get_guard("geofence_breach")(_inputs(pose_enu=(3.0, 4.0, 3.0)), {}, {"radius_m": 50.0})
        is False
    )
    assert get_guard("estimate_invalid")(_inputs(estimate_ok=False), {}, {}) is True
    assert get_guard("estimate_invalid")(_inputs(estimate_ok=True), {}, {}) is False
    assert get_guard("inputs_stale")(_inputs(input_ages={"odom": 2.0}), {}, {"t": 1.0}) is True
    assert get_guard("inputs_stale")(_inputs(input_ages={"odom": 0.2}), {}, {"t": 1.0}) is False
