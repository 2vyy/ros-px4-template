"""v1 mission behaviors. Each: (scratch, inputs, params) -> BehaviorResult."""

from __future__ import annotations

import math

from ros_px4_template_core.lib.frames import marker_world_from_drone
from ros_px4_template_core.lib.mission.commands import BehaviorResult, GoTo, Land
from ros_px4_template_core.lib.mission.detection import Detection, detections_for
from ros_px4_template_core.lib.mission.registry import behavior
from ros_px4_template_core.lib.mission.types import Inputs


def _latest(detections: tuple[Detection, ...], target_id: int | None) -> Detection | None:
    return max(detections_for(detections, target_id), key=lambda d: d.stamp, default=None)


@behavior("hold")
def hold(scratch: dict, inputs: Inputs, params: dict) -> BehaviorResult:
    if "x" not in scratch:
        scratch["x"] = float(params.get("x", inputs.pose_enu[0]))
        scratch["y"] = float(params.get("y", inputs.pose_enu[1]))
        scratch["z"] = float(params.get("z", inputs.pose_enu[2]))
        yaw_deg = params.get("yaw_deg")
        scratch["yaw"] = math.radians(float(yaw_deg)) if yaw_deg is not None else None
    tol = float(params.get("tolerance_m", 0.4))
    reached = math.dist(inputs.pose_enu, (scratch["x"], scratch["y"], scratch["z"])) <= tol
    return BehaviorResult(
        GoTo(scratch["x"], scratch["y"], scratch["z"], scratch["yaw"]), {"reached": reached}
    )


def _split_waypoint_entry(
    entry: tuple, index: int
) -> tuple[tuple[float, float, float], float | None]:
    """Split one waypoint entry into a 3-element position and an optional yaw (deg).

    Accepts only ``[x, y, z]`` or ``[x, y, z, yaw_deg]``; anything else is a
    malformed mission and fails fast at load/first-tick, not mid-flight.
    """
    if len(entry) == 3:
        x, y, z = (float(v) for v in entry)
        return (x, y, z), None
    if len(entry) == 4:
        x, y, z, yaw_deg = (float(v) for v in entry)
        return (x, y, z), yaw_deg
    raise ValueError(
        f"waypoint entry {index}: expected 3 ([x, y, z]) or 4 ([x, y, z, yaw_deg]) "
        f"elements, got {len(entry)}"
    )


def _step_waypoints(
    scratch: dict, inputs: Inputs, params: dict, wps: list[tuple[float, float, float]]
) -> tuple[int, bool, bool]:
    """Shared waypoint stepper. Returns (index, reached_current, done)."""
    tol = float(params.get("tolerance_m", 0.4))
    dwell = float(params.get("hold_s", 2.0))
    idx = scratch.setdefault("idx", 0)
    if idx >= len(wps):
        return idx, True, True
    at = math.dist(inputs.pose_enu, wps[idx]) <= tol
    if at:
        if scratch.get("hold_start") is None:
            scratch["hold_start"] = inputs.now
        elif inputs.now - scratch["hold_start"] >= dwell:
            scratch["idx"] = idx + 1
            scratch["hold_start"] = None
    else:
        scratch["hold_start"] = None
    return scratch["idx"], at, scratch["idx"] >= len(wps)


@behavior("follow_waypoints")
def follow_waypoints(scratch: dict, inputs: Inputs, params: dict) -> BehaviorResult:
    raw = params.get("waypoints", [])
    split = [_split_waypoint_entry(tuple(entry), i) for i, entry in enumerate(raw)]
    wps = [pos for pos, _yaw_deg in split]
    yaws_deg = [yaw_deg for _pos, yaw_deg in split]
    idx, at, done = _step_waypoints(scratch, inputs, params, wps)
    cur_idx = min(idx, len(wps) - 1) if wps else None
    cur = wps[cur_idx] if cur_idx is not None else inputs.pose_enu
    yaw_deg = yaws_deg[cur_idx] if cur_idx is not None else None
    yaw = math.radians(yaw_deg) if yaw_deg is not None else None
    return BehaviorResult(
        GoTo(*cur, yaw),
        {"reached": at, "waypoints_done": done, "waypoint_index": idx},
    )


def _lawnmower(params: dict) -> list[tuple[float, float, float]]:
    """Expanding boustrophedon waypoints around a center, at fixed altitude."""
    spacing = float(params.get("spacing_m", 2.0))
    legs = int(params.get("legs", 4))
    z = float(params.get("altitude_m", 3.0))
    cx, cy = (float(c) for c in params.get("center", (0.0, 0.0)))
    pts: list[tuple[float, float, float]] = []
    for i in range(1, legs + 1):
        reach = spacing * i
        sign = 1.0 if i % 2 == 1 else -1.0
        pts.append((cx + sign * reach, cy + spacing * (i - 1), z))
        pts.append((cx + sign * reach, cy + spacing * i, z))
    return pts


@behavior("search_lawnmower")
def search_lawnmower(scratch: dict, inputs: Inputs, params: dict) -> BehaviorResult:
    if "wps" not in scratch:
        scratch["wps"] = _lawnmower(params)
    wps = scratch["wps"]
    # Lawnmower advances as soon as each waypoint is reached (no dwell by default).
    step_params = {**params, "hold_s": float(params.get("hold_s", 0.0))}
    idx, _at, done = _step_waypoints(scratch, inputs, step_params, wps)
    cur = wps[min(idx, len(wps) - 1)] if wps else inputs.pose_enu
    return BehaviorResult(GoTo(*cur), {"search_complete": done})


@behavior("center_on_marker")
def center_on_marker(scratch: dict, inputs: Inputs, params: dict) -> BehaviorResult:
    tid = params.get("target_id")
    tid = int(tid) if tid is not None else None
    z = float(params.get("altitude_m", inputs.pose_enu[2]))
    tol = float(params.get("tolerance_m", 0.4))
    hold_s = float(params.get("hold_s", 10.0))
    det = _latest(inputs.detections, tid)
    if det is not None:
        tx, ty, _ = marker_world_from_drone(inputs.pose_enu, det.offset_body_flu, inputs.yaw_enu)
        scratch["tx"], scratch["ty"] = tx, ty
    else:
        tx = scratch.get("tx", inputs.pose_enu[0])
        ty = scratch.get("ty", inputs.pose_enu[1])
    err = math.hypot(inputs.pose_enu[0] - tx, inputs.pose_enu[1] - ty)
    centered = err <= tol
    if centered:
        scratch.setdefault("center_start", inputs.now)
    else:
        scratch.pop("center_start", None)
    hold_complete = "center_start" in scratch and inputs.now - scratch["center_start"] >= hold_s
    return BehaviorResult(
        GoTo(tx, ty, z),
        {"centering_error": err, "centered": centered, "hold_complete": hold_complete},
    )


@behavior("center_land")
def center_land(scratch: dict, inputs: Inputs, params: dict) -> BehaviorResult:
    """Visually servo over the marker, descend while centered, hand off to PX4 land.

    Descends only while the selected detection is FRESH (``marker_fresh_s``)
    AND the vehicle is centered (``tolerance_m``). On staleness or loss, the
    commanded altitude FREEZES (never climbs back) and the behavior signals
    ``marker_lost: True`` so the mission can divert to a ``reacquire`` state
    (via the ``marker_lost_signal`` guard) instead of blind-descending. The
    per-tick time delta used for descent integration is clamped to
    ``[0, max_dt_s]`` so a clock rewind cannot subtract distance and a stall
    cannot translate into an oversized descent step.

    Once ``Land`` is emitted, the hand-off is LATCHED for the episode: PX4
    owns the final descent and the marker inevitably leaves view near
    touchdown, so marker loss after hand-off must not divert to ``reacquire``.
    The behavior keeps emitting ``Land`` (``marker_lost: False``) until the
    state is exited (the ``disarmed`` guard fires on touchdown); a transition
    away clears the scratch, so a later episode starts fresh.
    """
    if scratch.get("land_latched"):
        return BehaviorResult(
            Land(),
            {
                "centering_error": float(scratch.get("last_err", 0.0)),
                "centered": True,
                "marker_lost": False,
                "land_commanded": True,
            },
        )

    tid = params.get("target_id")
    tid = int(tid) if tid is not None else None
    tol = float(params.get("tolerance_m", 0.3))
    descent_rate = float(params.get("descent_rate_m_s", 0.4))
    land_altitude = float(params.get("land_altitude_m", 0.7))
    min_altitude = float(params.get("min_altitude_m", 0.3))
    fresh_s = float(params.get("marker_fresh_s", 1.0))
    max_dt_s = float(params.get("max_dt_s", 0.5))

    det = _latest(inputs.detections, tid)
    if det is not None:
        tx, ty, _ = marker_world_from_drone(inputs.pose_enu, det.offset_body_flu, inputs.yaw_enu)
        scratch["tx"], scratch["ty"] = tx, ty
        scratch["last_det_stamp"] = det.stamp
    else:
        tx = scratch.get("tx", inputs.pose_enu[0])
        ty = scratch.get("ty", inputs.pose_enu[1])

    fresh = "last_det_stamp" in scratch and (inputs.now - scratch["last_det_stamp"]) <= fresh_s
    err = math.hypot(inputs.pose_enu[0] - tx, inputs.pose_enu[1] - ty)
    centered = err <= tol

    if "z_cmd" not in scratch:
        scratch["z_cmd"] = inputs.pose_enu[2]
    raw_dt = inputs.now - scratch.get("last_now", inputs.now)
    dt = min(max(raw_dt, 0.0), max_dt_s)
    scratch["last_now"] = inputs.now

    if fresh and centered:
        scratch["z_cmd"] = max(min_altitude, scratch["z_cmd"] - descent_rate * dt)

    signals = {
        "centering_error": err,
        "centered": centered,
        "marker_lost": not fresh,
    }
    if fresh and centered and inputs.pose_enu[2] <= land_altitude:
        scratch["land_latched"] = True
        scratch["last_err"] = err
        return BehaviorResult(Land(), {**signals, "land_commanded": True})
    return BehaviorResult(GoTo(tx, ty, scratch["z_cmd"]), {**signals, "land_commanded": False})


@behavior("goto_origin")
def goto_origin(scratch: dict, inputs: Inputs, params: dict) -> BehaviorResult:
    z = float(params.get("z", inputs.pose_enu[2]))
    tol = float(params.get("tolerance_m", 0.5))
    reached = math.dist(inputs.pose_enu, (0.0, 0.0, z)) <= tol
    return BehaviorResult(GoTo(0.0, 0.0, z), {"reached": reached})
