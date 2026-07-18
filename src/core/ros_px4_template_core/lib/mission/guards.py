"""v1 mission guards. Each: (inputs, signals, params) -> bool. Pure over the snapshot."""

from __future__ import annotations

import math
from typing import Any

from ros_px4_template_core.lib.mission.registry import guard
from ros_px4_template_core.lib.mission.types import Inputs


def _fresh(inputs: Inputs, target_id: int | None, t: float) -> bool:
    for d in inputs.detections:
        if target_id is not None and d.id != target_id:
            continue
        if inputs.now - d.stamp <= t:
            return True
    return False


def _as_float(value: Any, guard_name: str, param_name: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{guard_name}: '{param_name}' must be numeric, got {value!r}") from None


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


@guard("altitude_ceiling")
def altitude_ceiling(inputs: Inputs, signals: dict, params: dict) -> bool:
    """True at or above the ENU z ceiling. Intended for safety-tier transitions."""
    if "ceiling_m" not in params:
        raise ValueError("altitude_ceiling: required param 'ceiling_m' is missing")
    ceiling = _as_float(params["ceiling_m"], "altitude_ceiling", "ceiling_m")
    if ceiling <= 0.0:
        raise ValueError(f"altitude_ceiling: 'ceiling_m' must be > 0, got {ceiling}")
    return inputs.pose_enu[2] >= ceiling


@guard("time_budget")
def time_budget(inputs: Inputs, signals: dict, params: dict) -> bool:
    """True after the armed-time budget. Intended for safety-tier transitions."""
    if "budget_s" not in params:
        raise ValueError("time_budget: required param 'budget_s' is missing")
    budget = _as_float(params["budget_s"], "time_budget", "budget_s")
    if budget <= 0.0:
        raise ValueError(f"time_budget: 'budget_s' must be > 0, got {budget}")
    return inputs.mission_elapsed_s > budget


@guard("phase_timeout")
def phase_timeout(inputs: Inputs, signals: dict, params: dict) -> bool:
    """True after ``timeout_s`` seconds in the current state.

    Reads the engine-reserved ``state_elapsed_s`` signal; absent (load-time
    probing calls guards with ``signals={}``) it is treated as 0 and the guard
    is False.
    """
    if "timeout_s" not in params:
        raise ValueError("phase_timeout: required param 'timeout_s' is missing")
    timeout = _as_float(params["timeout_s"], "phase_timeout", "timeout_s")
    if timeout <= 0.0:
        raise ValueError(f"phase_timeout: 'timeout_s' must be > 0, got {timeout}")
    return float(signals.get("state_elapsed_s", 0.0)) > timeout


@guard("keep_out_box")
def keep_out_box(inputs: Inputs, signals: dict, params: dict) -> bool:
    """True inside an axis-aligned ENU box. Intended for safety-tier transitions."""
    required = ("x_min", "x_max", "y_min", "y_max")
    missing = [key for key in required if key not in params]
    if missing:
        raise ValueError(f"keep_out_box: required params missing: {missing}")
    x0 = _as_float(params["x_min"], "keep_out_box", "x_min")
    x1 = _as_float(params["x_max"], "keep_out_box", "x_max")
    y0 = _as_float(params["y_min"], "keep_out_box", "y_min")
    y1 = _as_float(params["y_max"], "keep_out_box", "y_max")
    z0 = _as_float(params.get("z_min", float("-inf")), "keep_out_box", "z_min")
    z1 = _as_float(params.get("z_max", float("inf")), "keep_out_box", "z_max")
    if x0 >= x1 or y0 >= y1 or z0 >= z1:
        raise ValueError("keep_out_box: each *_min must be < its *_max")
    x, y, z = inputs.pose_enu
    return (x0 <= x <= x1) and (y0 <= y <= y1) and (z0 <= z <= z1)


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


@guard("disarmed")
def disarmed(inputs: Inputs, signals: dict, params: dict) -> bool:
    return not inputs.armed


@guard("marker_lost_signal")
def marker_lost_signal(inputs: Inputs, signals: dict, params: dict) -> bool:
    """True when the current state's behavior signalled ``marker_lost``.

    Distinct from the inputs-only ``marker_lost`` guard: this reads the exact
    freshness computation the behavior made this tick (e.g. ``center_land``),
    so the mission transition can never disagree with what the behavior itself
    just decided.
    """
    return bool(signals.get("marker_lost"))
