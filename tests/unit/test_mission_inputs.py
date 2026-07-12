"""Characterization tests for the mission_manager -> Inputs snapshot seam (plan 057).

Pins the marker freshness/stability windows, z_eff altitude fusion, and
input_ages exactly as mission_manager._snapshot built them.
"""

from __future__ import annotations

from typing import Any

from ros_px4_template_core.lib.mission_inputs import MissionManagerState, build_inputs


def _state(**over: Any) -> MissionManagerState:
    base: dict[str, Any] = dict(
        pos_enu=(0.0, 0.0, 0.0),
        yaw_enu=0.0,
        have_odom=True,
        odom_time=0.0,
        armed=False,
        ctrl_alt=0.0,
        estimate_ok=True,
        marker_offset_body=None,
        marker_id_seen=0,
        marker_time=0.0,
        marker_stability=0,
        battery_remaining=None,
        have_battery=False,
        battery_time=0.0,
        failsafe_active=False,
        have_vehicle_status=False,
        vehicle_status_time=0.0,
    )
    base.update(over)
    return MissionManagerState(**base)


def _build(now: float, **over: Any):
    return build_inputs(now, _state(**over), takeoff_alt=3.0, takeoff_alt_tol=0.3)


def test_fresh_marker_has_detection_and_stability() -> None:
    inp, stab = _build(0.2, marker_offset_body=(1.0, 0.0, -3.0), marker_stability=5)
    assert len(inp.detections) == 1
    assert inp.detection_stability == {0: 5}
    assert stab == 5


def test_marker_in_fresh_but_not_stable_window_has_no_stability() -> None:
    inp, stab = _build(0.5, marker_offset_body=(1.0, 0.0, -3.0), marker_stability=5)
    assert len(inp.detections) == 1  # <= 1.0 s: still a detection
    assert inp.detection_stability == {}  # > 0.3 s: does not count toward stability
    assert stab == 5  # not reset (still within the 1.0 s window)


def test_stale_marker_drops_detection_and_resets_stability() -> None:
    inp, stab = _build(1.5, marker_offset_body=(1.0, 0.0, -3.0), marker_stability=5)
    assert inp.detections == ()
    assert inp.detection_stability == {}
    assert stab == 0  # persistent reset the caller writes back under the lock


def test_marker_freshness_boundaries_are_inclusive() -> None:
    # exactly 1.0 s: `now - marker_time > 1.0` is False, so it is still a detection
    inp, stab = _build(1.0, marker_offset_body=(1.0, 0.0, -3.0), marker_stability=4)
    assert len(inp.detections) == 1
    assert stab == 4
    assert inp.detection_stability == {}  # 1.0 > 0.3 stable window
    # exactly 0.3 s: `<= _STABLE_FRESH_S` is inclusive, so stability is present
    inp2, _ = _build(0.3, marker_offset_body=(1.0, 0.0, -3.0), marker_stability=4)
    assert inp2.detection_stability == {0: 4}


def test_z_eff_is_max_of_pose_and_ctrl_alt() -> None:
    inp, _ = _build(0.0, pos_enu=(0.0, 0.0, 1.0), ctrl_alt=2.9)
    assert inp.pose_enu[2] == 2.9
    assert inp.altitude_ok is True  # 2.9 >= 3.0 - 0.3
    inp2, _ = _build(0.0, pos_enu=(0.0, 0.0, 1.0), ctrl_alt=1.0)
    assert inp2.pose_enu[2] == 1.0
    assert inp2.altitude_ok is False


def test_input_ages_inf_when_never_seen_else_delta() -> None:
    inp, _ = _build(
        10.0,
        have_odom=True,
        odom_time=8.0,
        have_battery=False,
        have_vehicle_status=True,
        vehicle_status_time=9.5,
    )
    assert inp.input_ages["odom"] == 2.0
    assert inp.input_ages["battery"] == float("inf")
    assert inp.input_ages["vehicle_status"] == 0.5


def test_battery_remaining_passes_through() -> None:
    inp, _ = _build(0.0, battery_remaining=None)
    assert inp.battery_remaining is None
    inp2, _ = _build(0.0, battery_remaining=0.42)
    assert inp2.battery_remaining == 0.42
