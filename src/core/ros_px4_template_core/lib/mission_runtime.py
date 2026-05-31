"""Mission phase logic — single tick() function, no class FSM."""

from __future__ import annotations

from dataclasses import dataclass, field

from ros_px4_template_core.lib import events
from ros_px4_template_core.lib.waypoint_mission import (
    EnuPoint,
    WaypointMission,
    current_waypoint,
    reached,
)

PHASE_WAIT_ARM_ALTITUDE = "wait_arm_altitude"
PHASE_FOLLOW_PATH = "follow_path"
PHASE_MARKER_HOVER = "marker_hover"
PHASE_DONE = "done"


@dataclass
class MissionContext:
    phase: str = PHASE_WAIT_ARM_ALTITUDE
    waypoint_index: int = 0
    waypoint_hold_start: float | None = None
    marker_hover_start: float | None = None
    target: EnuPoint = field(default_factory=lambda: EnuPoint(0.0, 0.0, 0.0))
    events: list[dict[str, object]] = field(default_factory=list)


@dataclass(frozen=True)
class TickInputs:
    now: float
    pos_enu: tuple[float, float, float]
    controller_armed: bool
    altitude_ok: bool
    marker_offset_enu: tuple[float, float] | None = None
    marker_hold_s: float = 10.0


@dataclass(frozen=True)
class TickOutput:
    target: EnuPoint
    phase: str
    waypoint_index: int


def _emit(ctx: MissionContext, event: str, **fields: object) -> None:
    ctx.events.append({"event": event, **fields})


def _set_phase(ctx: MissionContext, new_phase: str) -> None:
    if ctx.phase != new_phase:
        _emit(ctx, events.PHASE_CHANGE, **{"from": ctx.phase, "to": new_phase})
        ctx.phase = new_phase


def _advance_waypoint(ctx: MissionContext, mission: WaypointMission, now: float) -> None:
    idx = ctx.waypoint_index
    wp = current_waypoint(mission, idx)
    if wp is None:
        return
    _emit(
        ctx,
        events.WAYPOINT_REACHED,
        index=idx,
        x=wp.x,
        y=wp.y,
        z=wp.z,
    )
    ctx.waypoint_index = idx + 1
    ctx.waypoint_hold_start = None
    nxt = current_waypoint(mission, ctx.waypoint_index)
    if nxt is not None:
        ctx.target = nxt


def tick(ctx: MissionContext, mission: WaypointMission, inputs: TickInputs) -> TickOutput:
    """Advance mission one step; append structured events to ctx.events."""
    tol = mission.defaults.tolerance_m
    hold_s = mission.defaults.hold_s
    pos = inputs.pos_enu

    if ctx.phase == PHASE_WAIT_ARM_ALTITUDE:
        first = current_waypoint(mission, 0) or EnuPoint(0.0, 0.0, 0.0)
        ctx.target = first
        if inputs.controller_armed and inputs.altitude_ok:
            _set_phase(ctx, PHASE_FOLLOW_PATH)
            ctx.waypoint_index = 0
            ctx.target = first

    elif ctx.phase == PHASE_FOLLOW_PATH:
        wp = current_waypoint(mission, ctx.waypoint_index)
        if wp is None:
            # Path finished — wait for marker or go to done
            if inputs.marker_offset_enu is not None:
                _set_phase(ctx, PHASE_MARKER_HOVER)
            else:
                _set_phase(ctx, PHASE_DONE)
                _emit(ctx, events.MISSION_DONE)
        else:
            ctx.target = wp
            if reached(pos, wp, tol, z_tolerance_m=mission.defaults.z_tolerance_m):
                if ctx.waypoint_hold_start is None:
                    ctx.waypoint_hold_start = inputs.now
                elif inputs.now - ctx.waypoint_hold_start >= hold_s:
                    _advance_waypoint(ctx, mission, inputs.now)
                    if current_waypoint(mission, ctx.waypoint_index) is None:
                        if inputs.marker_offset_enu is not None:
                            _set_phase(ctx, PHASE_MARKER_HOVER)
                        else:
                            _set_phase(ctx, PHASE_DONE)
                            _emit(ctx, events.MISSION_DONE)
            else:
                ctx.waypoint_hold_start = None

    elif ctx.phase == PHASE_MARKER_HOVER:
        offset = inputs.marker_offset_enu
        if offset is not None:
            ctx.target = EnuPoint(
                x=inputs.pos_enu[0] + offset[0],
                y=inputs.pos_enu[1] + offset[1],
                z=ctx.target.z,
            )
        if ctx.marker_hover_start is None:
            ctx.marker_hover_start = inputs.now
            _emit(ctx, events.MARKER_HOVER_START)
        elif inputs.now - ctx.marker_hover_start >= inputs.marker_hold_s:
            _set_phase(ctx, PHASE_DONE)
            _emit(ctx, events.MISSION_DONE)

    elif ctx.phase == PHASE_DONE:
        pass

    return TickOutput(
        target=ctx.target,
        phase=ctx.phase,
        waypoint_index=ctx.waypoint_index,
    )
