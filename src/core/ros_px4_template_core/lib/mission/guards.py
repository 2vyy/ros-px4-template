"""v1 mission guards. Each: (inputs, signals, params) -> bool. Pure over the snapshot."""

from __future__ import annotations

import math

from ros_px4_template_core.lib.mission.registry import guard
from ros_px4_template_core.lib.mission.types import Inputs


def _fresh(inputs: Inputs, target_id: int | None, t: float) -> bool:
    for d in inputs.detections:
        if target_id is not None and d.id != target_id:
            continue
        if inputs.now - d.stamp <= t:
            return True
    return False


@guard("armed_at_altitude")
def armed_at_altitude(inputs: Inputs, signals: dict, params: dict) -> bool:
    return bool(inputs.armed and inputs.altitude_ok)


@guard("waypoints_done")
def waypoints_done(inputs: Inputs, signals: dict, params: dict) -> bool:
    return bool(signals.get("waypoints_done"))


@guard("reached")
def reached(inputs: Inputs, signals: dict, params: dict) -> bool:
    return bool(signals.get("reached"))


@guard("hold_complete")
def hold_complete(inputs: Inputs, signals: dict, params: dict) -> bool:
    return bool(signals.get("hold_complete"))


@guard("search_complete")
def search_complete(inputs: Inputs, signals: dict, params: dict) -> bool:
    return bool(signals.get("search_complete"))


@guard("marker_fresh")
def marker_fresh(inputs: Inputs, signals: dict, params: dict) -> bool:
    tid = params.get("id")
    return _fresh(inputs, int(tid) if tid is not None else None, float(params.get("t", 1.0)))


@guard("marker_stable")
def marker_stable(inputs: Inputs, signals: dict, params: dict) -> bool:
    tid = params.get("id")
    n = int(params.get("n", 5))
    if tid is None:
        return any(c >= n for c in inputs.detection_stability.values())
    return inputs.detection_stability.get(int(tid), 0) >= n


@guard("marker_lost")
def marker_lost(inputs: Inputs, signals: dict, params: dict) -> bool:
    tid = params.get("id")
    return not _fresh(inputs, int(tid) if tid is not None else None, float(params.get("t", 3.0)))


@guard("geofence_breach")
def geofence_breach(inputs: Inputs, signals: dict, params: dict) -> bool:
    radius = float(params.get("radius_m", 50.0))
    return math.hypot(inputs.pose_enu[0], inputs.pose_enu[1]) >= radius


@guard("estimate_invalid")
def estimate_invalid(inputs: Inputs, signals: dict, params: dict) -> bool:
    return not inputs.estimate_ok


@guard("inputs_stale")
def inputs_stale(inputs: Inputs, signals: dict, params: dict) -> bool:
    key = str(params.get("key", "odom"))
    return inputs.input_ages.get(key, float("inf")) > float(params.get("t", 1.0))


@guard("battery_low")
def battery_low(inputs: Inputs, signals: dict, params: dict) -> bool:
    frac = float(params.get("frac", 0.2))
    if not 0.0 <= frac <= 1.0:
        raise ValueError(f"battery_low: 'frac' must be within [0, 1], got {frac}")
    max_age_s = float(params.get("max_age_s", 5.0))
    if inputs.battery_remaining is None:
        return False
    age = inputs.input_ages.get("battery", float("inf"))
    if age > max_age_s:
        return False
    return inputs.battery_remaining <= frac


@guard("failsafe_active")
def failsafe_active(inputs: Inputs, signals: dict, params: dict) -> bool:
    return bool(inputs.failsafe_active)
