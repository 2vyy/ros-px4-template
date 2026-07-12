"""Kinematic engine-level mission simulation (rclpy-free).

Drives the pure mission engine (:func:`tick`) over a crude straight-line
kinematic model so an agent can verify a mission's GRAPH LOGIC in under a
second, with no sim boot: transitions fire when their conditions occur, the
happy path walks takeoff -> ... -> terminal, and a typo'd guard that never
fires shows up as a stall (``terminated == False``).

This verifies LOGIC, not flight dynamics. The model is intentionally crude
(straight-line chase at a fixed speed, instant arm on the first setpoint); the
live scenario tier remains the flight gate. Anyone tempted to add real dynamics
should promote the case to a scenario instead.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field

from ros_px4_template_core.lib.frames import enu_offset_to_body_flu
from ros_px4_template_core.lib.mission.commands import GoTo, Land
from ros_px4_template_core.lib.mission.detection import Detection
from ros_px4_template_core.lib.mission.engine import MissionContext, tick
from ros_px4_template_core.lib.mission.types import Inputs, Mission

# Defaults mirror what mission_manager declares (mission_manager.py:78-79) so
# the altitude gate the engine sees matches runtime.
_TAKEOFF_ALTITUDE_M = 3.0
_ALTITUDE_TOLERANCE_M = 0.3


@dataclass
class SimVehicle:
    """Mutable per-tick vehicle state; a ``script`` hook may read or override it."""

    now: float = 0.0
    pose_enu: tuple[float, float, float] = (0.0, 0.0, 0.0)
    yaw_enu: float = 0.0
    armed: bool = False
    estimate_ok: bool = True
    battery_remaining: float = 1.0
    failsafe_active: bool = False
    detections: tuple[Detection, ...] = ()
    detection_stability: dict[int, int] = field(default_factory=dict)
    input_ages: dict[str, float] = field(
        default_factory=lambda: {"odom": 0.0, "battery": 0.0, "vehicle_status": 0.0}
    )


@dataclass
class SimResult:
    """Outcome of a :func:`simulate` run."""

    reached_states: list[str]  # states in first-visit order
    final_state: str
    ticks: int
    terminated: bool  # reached a terminal state
    landed: bool  # a Land command was emitted
    final_pose: tuple[float, float, float]
    events: list[dict]  # accumulated ctx.events (TRANSITIONs etc.)


def marker_below_script(
    target_id: int = 0, stability_n: int = 5
) -> Callable[[float, SimVehicle], None]:
    """A ``script`` that plants a fresh, stable detection directly below the vehicle.

    Enough to exercise every marker guard and behavior (``marker_stable``,
    ``marker_fresh``, ``center_on_marker``, ``center_land``) so a marker mission
    progresses. It does NOT model search-and-find geometry (the drone is always
    already centered over the marker); that realism lives in the live tier. Use
    :func:`marker_at_script` when a test needs a fixed world-anchored marker.
    """

    def _script(now: float, v: SimVehicle) -> None:
        v.detections = (
            Detection(id=target_id, offset_body_flu=(0.0, 0.0, -v.pose_enu[2]), stamp=now),
        )
        v.detection_stability = {target_id: stability_n}

    return _script


def marker_at_script(
    marker_enu: tuple[float, float, float], target_id: int = 0, stability_n: int = 5
) -> Callable[[float, SimVehicle], None]:
    """A ``script`` that plants a fresh, stable detection of a FIXED world marker.

    The body-FLU offset is derived from the vehicle's current pose and yaw with
    :func:`enu_offset_to_body_flu`, so the drone must actually fly over the
    marker for ``center_*`` behaviors to converge -- exercising the offset
    geometry, not short-circuiting it.
    """
    mx, my, mz = (float(c) for c in marker_enu)

    def _script(now: float, v: SimVehicle) -> None:
        dx, dy, dz = v.pose_enu
        forward, left = enu_offset_to_body_flu((mx - dx, my - dy, mz - dz), v.yaw_enu)
        v.detections = (
            Detection(id=target_id, offset_body_flu=(forward, left, mz - dz), stamp=now),
        )
        v.detection_stability = {target_id: stability_n}

    return _script


def _step_toward(
    pose: tuple[float, float, float], target: tuple[float, float, float], step: float
) -> tuple[float, float, float]:
    px, py, pz = pose
    tx, ty, tz = target
    dx, dy, dz = tx - px, ty - py, tz - pz
    dist = math.sqrt(dx * dx + dy * dy + dz * dz)
    if dist <= step or dist == 0.0:
        return (tx, ty, tz)
    f = step / dist
    return (px + dx * f, py + dy * f, pz + dz * f)


def simulate(
    mission: Mission,
    *,
    tick_rate_hz: float = 10.0,
    max_ticks: int = 3000,  # 300 sim-seconds at 10 Hz
    speed_m_s: float = 2.0,  # kinematic chase speed toward GoTo targets
    start_pose: tuple[float, float, float] = (0.0, 0.0, 0.0),
    takeoff_altitude_m: float = _TAKEOFF_ALTITUDE_M,
    altitude_tolerance_m: float = _ALTITUDE_TOLERANCE_M,
    land_speed_m_s: float = 0.5,
    script: Callable[[float, SimVehicle], None] | None = None,
) -> SimResult:
    """Tick ``mission`` to a terminal state (or ``max_ticks``) over a kinematic model.

    Each tick: (optional) ``script`` mutates the vehicle, an :class:`Inputs`
    snapshot is built from the vehicle, :func:`tick` advances the FSM, and the
    returned command is applied kinematically -- ``GoTo`` chases the target at
    ``speed_m_s``, ``Land`` descends at ``land_speed_m_s`` and disarms on
    touchdown (modelling PX4 AUTO_LAND so ``disarmed`` guards fire).
    """
    dt = 1.0 / tick_rate_hz
    v = SimVehicle(pose_enu=(float(start_pose[0]), float(start_pose[1]), float(start_pose[2])))
    ctx = MissionContext(state=mission.initial)
    reached: list[str] = [mission.initial]
    landed = False

    for i in range(max_ticks):
        if script is not None:
            script(v.now, v)

        altitude_ok = v.pose_enu[2] >= takeoff_altitude_m - altitude_tolerance_m
        inputs = Inputs(
            now=v.now,
            pose_enu=v.pose_enu,
            yaw_enu=v.yaw_enu,
            armed=v.armed,
            altitude_ok=altitude_ok,
            estimate_ok=v.estimate_ok,
            detections=v.detections,
            detection_stability=dict(v.detection_stability),
            input_ages=dict(v.input_ages),
            battery_remaining=v.battery_remaining,
            failsafe_active=v.failsafe_active,
        )
        cmd = tick(ctx, mission, inputs)
        if ctx.state not in reached:
            reached.append(ctx.state)

        if isinstance(cmd, GoTo):
            v.armed = True  # first setpoint arms; the FSM under test is the mission, not offboard
            v.pose_enu = _step_toward(v.pose_enu, (cmd.x, cmd.y, cmd.z), speed_m_s * dt)
        elif isinstance(cmd, Land):
            landed = True
            x, y, z = v.pose_enu
            z = max(0.0, z - land_speed_m_s * dt)
            v.pose_enu = (x, y, z)
            if z <= 0.05:
                v.armed = False
        # Hold (never emitted by v1 behaviors): hold position.

        v.now += dt

        if ctx.state in mission.terminal:
            return SimResult(reached, ctx.state, i + 1, True, landed, v.pose_enu, list(ctx.events))

    return SimResult(reached, ctx.state, max_ticks, False, landed, v.pose_enu, list(ctx.events))
