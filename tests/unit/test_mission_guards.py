"""Unit tests for mission guards."""

from __future__ import annotations

import pytest
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
    battery_remaining: float | None = None,
    failsafe_active: bool = False,
    mission_elapsed_s: float = 0.0,
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
        battery_remaining=battery_remaining,
        failsafe_active=failsafe_active,
        mission_elapsed_s=mission_elapsed_s,
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


def test_battery_low_default_fields() -> None:
    # battery_remaining defaults to None, failsafe_active defaults to False.
    ins = _inputs()
    assert ins.battery_remaining is None
    assert ins.failsafe_active is False
    assert get_guard("battery_low")(ins, {}, {}) is False
    assert get_guard("failsafe_active")(ins, {}, {}) is False


def test_battery_low_threshold_boundaries() -> None:
    fresh_ages = {"odom": 0.0, "battery": 0.0}
    at_threshold = _inputs(battery_remaining=0.2, input_ages=fresh_ages)
    just_above = _inputs(battery_remaining=0.21, input_ages=fresh_ages)
    just_below = _inputs(battery_remaining=0.19, input_ages=fresh_ages)
    assert get_guard("battery_low")(at_threshold, {}, {}) is True
    assert get_guard("battery_low")(just_above, {}, {}) is False
    assert get_guard("battery_low")(just_below, {}, {}) is True


def test_battery_low_custom_threshold() -> None:
    fresh_ages = {"odom": 0.0, "battery": 0.0}
    ins = _inputs(battery_remaining=0.5, input_ages=fresh_ages)
    assert get_guard("battery_low")(ins, {}, {"frac": 0.6}) is True
    assert get_guard("battery_low")(ins, {}, {"frac": 0.4}) is False


def test_battery_low_unknown_battery_is_false() -> None:
    ins = _inputs(battery_remaining=None, input_ages={"odom": 0.0, "battery": 0.0})
    assert get_guard("battery_low")(ins, {}, {}) is False


def test_battery_low_stale_battery_is_false() -> None:
    ins = _inputs(battery_remaining=0.05, input_ages={"odom": 0.0, "battery": 10.0})
    assert get_guard("battery_low")(ins, {}, {}) is False
    assert get_guard("battery_low")(ins, {}, {"max_age_s": 20.0}) is True


def test_battery_low_invalid_frac_raises() -> None:
    ins = _inputs(battery_remaining=0.1, input_ages={"odom": 0.0, "battery": 0.0})
    with pytest.raises(ValueError, match="frac"):
        get_guard("battery_low")(ins, {}, {"frac": 1.5})
    with pytest.raises(ValueError, match="frac"):
        get_guard("battery_low")(ins, {}, {"frac": -0.1})


def test_failsafe_active_guard() -> None:
    assert get_guard("failsafe_active")(_inputs(failsafe_active=True), {}, {}) is True
    assert get_guard("failsafe_active")(_inputs(failsafe_active=False), {}, {}) is False


def test_disarmed_guard() -> None:
    assert get_guard("disarmed")(_inputs(armed=True), {}, {}) is False
    assert get_guard("disarmed")(_inputs(armed=False), {}, {}) is True


def test_marker_lost_signal_guard() -> None:
    assert get_guard("marker_lost_signal")(_inputs(), {"marker_lost": True}, {}) is True
    assert get_guard("marker_lost_signal")(_inputs(), {"marker_lost": False}, {}) is False
    assert get_guard("marker_lost_signal")(_inputs(), {}, {}) is False


def test_altitude_ceiling_boundaries() -> None:
    ceiling = get_guard("altitude_ceiling")
    assert ceiling(_inputs(pose_enu=(0.0, 0.0, 9.9)), {}, {"ceiling_m": 10.0}) is False
    assert ceiling(_inputs(pose_enu=(0.0, 0.0, 10.0)), {}, {"ceiling_m": 10.0}) is True
    assert ceiling(_inputs(pose_enu=(0.0, 0.0, 10.1)), {}, {"ceiling_m": 10.0}) is True


@pytest.mark.parametrize(
    "params", [{}, {"ceiling_m": 0.0}, {"ceiling_m": -1.0}, {"ceiling_m": None}]
)
def test_altitude_ceiling_rejects_invalid_params(params: dict) -> None:
    with pytest.raises(ValueError, match="altitude_ceiling"):
        get_guard("altitude_ceiling")(_inputs(), {}, params)


def test_time_budget_uses_armed_elapsed_time() -> None:
    budget = get_guard("time_budget")
    assert budget(_inputs(mission_elapsed_s=0.0), {}, {"budget_s": 300.0}) is False
    assert budget(_inputs(mission_elapsed_s=300.0), {}, {"budget_s": 300.0}) is False
    assert budget(_inputs(mission_elapsed_s=301.0), {}, {"budget_s": 300.0}) is True


@pytest.mark.parametrize("params", [{}, {"budget_s": 0.0}, {"budget_s": -1.0}, {"budget_s": None}])
def test_time_budget_rejects_invalid_params(params: dict) -> None:
    with pytest.raises(ValueError, match="time_budget"):
        get_guard("time_budget")(_inputs(), {}, params)


def test_keep_out_box_boundaries_and_optional_altitude() -> None:
    keep_out = get_guard("keep_out_box")
    xy = {"x_min": -1.0, "x_max": 1.0, "y_min": -2.0, "y_max": 2.0}
    assert keep_out(_inputs(pose_enu=(0.0, 0.0, 50.0)), {}, xy) is True
    assert keep_out(_inputs(pose_enu=(1.0, 2.0, 0.0)), {}, xy) is True
    assert keep_out(_inputs(pose_enu=(1.1, 0.0, 0.0)), {}, xy) is False

    xyz = {**xy, "z_min": 0.0, "z_max": 3.0}
    assert keep_out(_inputs(pose_enu=(0.0, 0.0, 3.1)), {}, xyz) is False


@pytest.mark.parametrize(
    "params",
    [
        {},
        {"x_min": 0.0, "x_max": 0.0, "y_min": -1.0, "y_max": 1.0},
        {"x_min": -1.0, "x_max": 1.0, "y_min": 2.0, "y_max": 1.0},
        {"x_min": None, "x_max": 1.0, "y_min": -1.0, "y_max": 1.0},
        {
            "x_min": -1.0,
            "x_max": 1.0,
            "y_min": -1.0,
            "y_max": 1.0,
            "z_min": 4.0,
            "z_max": 3.0,
        },
    ],
)
def test_keep_out_box_rejects_missing_or_inverted_bounds(params: dict) -> None:
    with pytest.raises(ValueError, match="keep_out_box"):
        get_guard("keep_out_box")(_inputs(), {}, params)
