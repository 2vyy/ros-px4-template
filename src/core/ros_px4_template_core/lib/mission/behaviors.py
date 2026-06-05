"""v1 mission behaviors. Each: (scratch, inputs, params) -> BehaviorResult."""

from __future__ import annotations

import math

from ros_px4_template_core.lib.mission.commands import BehaviorResult, GoTo
from ros_px4_template_core.lib.mission.detection import Detection, body_flu_to_enu_offset
from ros_px4_template_core.lib.mission.registry import behavior
from ros_px4_template_core.lib.mission.types import Inputs


def _latest(detections: tuple[Detection, ...], target_id: int | None) -> Detection | None:
    best: Detection | None = None
    for d in detections:
        if target_id is not None and d.id != target_id:
            continue
        if best is None or d.stamp >= best.stamp:
            best = d
    return best


@behavior("hold")
def hold(scratch: dict, inputs: Inputs, params: dict) -> BehaviorResult:
    if "x" not in scratch:
        scratch["x"] = float(params.get("x", inputs.pose_enu[0]))
        scratch["y"] = float(params.get("y", inputs.pose_enu[1]))
        scratch["z"] = float(params.get("z", inputs.pose_enu[2]))
    tol = float(params.get("tolerance_m", 0.4))
    reached = math.dist(inputs.pose_enu, (scratch["x"], scratch["y"], scratch["z"])) <= tol
    return BehaviorResult(GoTo(scratch["x"], scratch["y"], scratch["z"]), {"reached": reached})


def _step_waypoints(
    scratch: dict, inputs: Inputs, params: dict, wps: list
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
    wps = [tuple(map(float, p)) for p in params.get("waypoints", [])]
    idx, at, done = _step_waypoints(scratch, inputs, params, wps)
    cur = wps[min(idx, len(wps) - 1)] if wps else inputs.pose_enu
    return BehaviorResult(
        GoTo(*cur),
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
        east, north = body_flu_to_enu_offset(det.offset_body_flu, inputs.yaw_enu)
        tx = inputs.pose_enu[0] + east
        ty = inputs.pose_enu[1] + north
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


@behavior("goto_origin")
def goto_origin(scratch: dict, inputs: Inputs, params: dict) -> BehaviorResult:
    z = float(params.get("z", inputs.pose_enu[2]))
    tol = float(params.get("tolerance_m", 0.5))
    reached = math.dist(inputs.pose_enu, (0.0, 0.0, z)) <= tol
    return BehaviorResult(GoTo(0.0, 0.0, z), {"reached": reached})
