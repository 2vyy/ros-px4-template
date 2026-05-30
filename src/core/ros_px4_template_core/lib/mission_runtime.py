"""Mission phase logic — single tick() function, no class FSM."""

from __future__ import annotations

from dataclasses import dataclass, field

from ros_px4_template_core.lib import events
from ros_px4_template_core.lib.marker_target import MarkerTracker, marker_hover_target, pose_to_enu
from ros_px4_template_core.lib.waypoint_mission import (
    EnuPoint,
    WaypointMission,
    current_waypoint,
    reached,
)

PHASE_WAIT_ARM_ALTITUDE = "wait_arm_altitude"
PHASE_FOLLOW_PATH = "follow_path"
PHASE_HOVER_MARKER = "hover_marker"
PHASE_DONE = "done"


@dataclass
class MissionContext:
    phase: str = PHASE_WAIT_ARM_ALTITUDE
    waypoint_index: int = 0
    waypoint_hold_start: float | None = None
    hover_start: float | None = None
    marker_seen: bool = False
    marker_tracker: MarkerTracker = field(default_factory=MarkerTracker)
    target: EnuPoint = field(default_factory=lambda: EnuPoint(0.0, 0.0, 0.0))
    events: list[dict[str, object]] = field(default_factory=list)


@dataclass(frozen=True)
class TickInputs:
    now: float
    pos_enu: tuple[float, float, float]
    controller_armed: bool
    altitude_ok: bool
    marker_valid: bool
    marker_position: tuple[float, float, float] | None


@dataclass(frozen=True)
class TickOutput:
    target: EnuPoint
    phase: str
    waypoint_index: int
    marker_seen: bool


def _emit(ctx: MissionContext, event: str, **fields: object) -> None:
    ctx.events.append({"event": event, **fields})


def _set_phase(ctx: MissionContext, new_phase: str) -> None:
    if ctx.phase != new_phase:
        _emit(ctx, events.PHASE_CHANGE, **{"from": ctx.phase, "to": new_phase})
        ctx.phase = new_phase


def _enter_hover_marker(
    ctx: MissionContext,
    mission: WaypointMission,
    marker_position: tuple[float, float, float],
) -> None:
    cfg = mission.marker
    if cfg is None:
        return
    _set_phase(ctx, PHASE_HOVER_MARKER)
    m = pose_to_enu(marker_position)
    ctx.target = marker_hover_target(m, cfg)
    _emit(ctx, events.MARKER_ACQUIRED, marker_id=0)


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
    if inputs.marker_valid:
        ctx.marker_tracker.note_valid(inputs.now)
    else:
        ctx.marker_tracker.note_invalid(inputs.now)

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
            # Path finished — marker missions wait here until the marker gate passes.
            if mission.marker is None:
                _set_phase(ctx, PHASE_DONE)
                _emit(ctx, events.MISSION_DONE)
            elif (
                inputs.marker_valid
                and inputs.marker_position is not None
                and ctx.marker_tracker.acquired(mission.marker)
            ):
                _enter_hover_marker(ctx, mission, inputs.marker_position)
        else:
            ctx.target = wp
            if reached(pos, wp, tol, z_tolerance_m=mission.defaults.z_tolerance_m):
                if ctx.waypoint_hold_start is None:
                    ctx.waypoint_hold_start = inputs.now
                elif inputs.now - ctx.waypoint_hold_start >= hold_s:
                    _advance_waypoint(ctx, mission, inputs.now)
                    if current_waypoint(mission, ctx.waypoint_index) is None:
                        if mission.marker is None:
                            _set_phase(ctx, PHASE_DONE)
                            _emit(ctx, events.MISSION_DONE)
                        elif (
                            inputs.marker_valid
                            and inputs.marker_position is not None
                            and ctx.marker_tracker.acquired(mission.marker)
                        ):
                            _enter_hover_marker(ctx, mission, inputs.marker_position)
            else:
                ctx.waypoint_hold_start = None

            # Early marker intercept only while waypoints remain (avoids duplicate
            # MARKER_ACQUIRED when wp is already None — B14) and only if we haven't
            # already entered hover_marker this tick (avoids duplicate — B21).
            if (
                ctx.phase != PHASE_HOVER_MARKER
                and mission.marker is not None
                and inputs.marker_valid
                and inputs.marker_position is not None
                and ctx.marker_tracker.acquired(mission.marker)
            ):
                _enter_hover_marker(ctx, mission, inputs.marker_position)

    elif ctx.phase == PHASE_HOVER_MARKER:
        cfg = mission.marker
        if cfg is None:
            _set_phase(ctx, PHASE_DONE)
        else:
            if inputs.marker_valid and inputs.marker_position is not None:
                ctx.marker_tracker.note_valid(inputs.now)
                m = pose_to_enu(inputs.marker_position)
                ctx.target = marker_hover_target(m, cfg)
                ctx.marker_seen = True
            else:
                ctx.marker_tracker.note_invalid(inputs.now)
                if ctx.marker_tracker.lost_debounced(cfg, inputs.now):
                    _emit(ctx, events.MARKER_LOST)
                    ctx.marker_seen = False

            if ctx.hover_start is None and reached(
                pos, ctx.target, tol, z_tolerance_m=mission.defaults.z_tolerance_m
            ):
                ctx.hover_start = inputs.now
            if ctx.hover_start is not None:
                if inputs.now - ctx.hover_start >= cfg.hold_duration_s:
                    _set_phase(ctx, PHASE_DONE)
                    _emit(ctx, events.MISSION_DONE)

    elif ctx.phase == PHASE_DONE:
        pass

    return TickOutput(
        target=ctx.target,
        phase=ctx.phase,
        waypoint_index=ctx.waypoint_index,
        marker_seen=ctx.marker_seen,
    )
