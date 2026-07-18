"""Pure builder for the mission engine's ``Inputs`` snapshot -- no ROS.

The raw-ROS -> ``Inputs`` seam extracted verbatim from
``mission_manager._snapshot``: marker staleness windows, the ``z_eff`` altitude
fusion, and ``input_ages``. Kept pure so the boundaries have unit coverage
(the engine is only tested GIVEN a well-formed ``Inputs``).

Characterization -- reproduces today's semantics exactly, including the
persistent stability reset: a stale/absent marker zeroes ``marker_stability``,
and the caller writes the returned value back under its lock so the zero
persists across ticks.
"""

from __future__ import annotations

from dataclasses import dataclass

from ros_px4_template_core.lib.mission.detection import Detection
from ros_px4_template_core.lib.mission.types import Inputs

# A detection is fresh enough to be a detection at all within this window, and
# counts toward stability only within the tighter _STABLE_FRESH_S window.
_MARKER_FRESH_S = 1.0


@dataclass
class MissionManagerState:
    """Plain snapshot of mission_manager's locked fields (copied under the lock)."""

    pos_enu: tuple[float, float, float]
    yaw_enu: float
    have_odom: bool
    odom_time: float
    armed: bool
    first_armed_time: float | None
    ctrl_alt: float
    estimate_ok: bool
    marker_offset_body: tuple[float, float, float] | None
    marker_id_seen: int
    marker_time: float
    marker_stability: int
    battery_remaining: float | None
    have_battery: bool
    battery_time: float
    failsafe_active: bool
    have_vehicle_status: bool
    vehicle_status_time: float


def build_inputs(
    now: float,
    s: MissionManagerState,
    *,
    takeoff_alt: float,
    takeoff_alt_tol: float,
    stable_fresh_s: float = 0.3,
) -> tuple[Inputs, int]:
    """Build the engine ``Inputs`` from a locked state snapshot.

    Returns ``(inputs, marker_stability)``; the caller persists
    ``marker_stability`` (zeroed on a stale/absent marker) back under its lock.
    """
    marker_stability = s.marker_stability
    if s.marker_offset_body is None or now - s.marker_time > _MARKER_FRESH_S:
        marker_stability = 0

    dets: tuple[Detection, ...] = ()
    stability: dict[int, int] = {}
    if s.marker_offset_body is not None and now - s.marker_time <= _MARKER_FRESH_S:
        dets = (
            Detection(
                id=s.marker_id_seen,
                offset_body_flu=s.marker_offset_body,
                stamp=s.marker_time,
            ),
        )
        if now - s.marker_time <= stable_fresh_s:
            stability = {s.marker_id_seen: marker_stability}

    z_eff = max(s.pos_enu[2], s.ctrl_alt)
    inputs = Inputs(
        now=now,
        pose_enu=(s.pos_enu[0], s.pos_enu[1], z_eff),
        yaw_enu=s.yaw_enu,
        armed=s.armed,
        altitude_ok=z_eff >= takeoff_alt - takeoff_alt_tol,
        estimate_ok=s.estimate_ok,
        detections=dets,
        detection_stability=stability,
        input_ages={
            "odom": (now - s.odom_time) if s.have_odom else float("inf"),
            "battery": (now - s.battery_time) if s.have_battery else float("inf"),
            "vehicle_status": (
                (now - s.vehicle_status_time) if s.have_vehicle_status else float("inf")
            ),
        },
        battery_remaining=s.battery_remaining,
        failsafe_active=s.failsafe_active,
        mission_elapsed_s=((now - s.first_armed_time) if s.first_armed_time is not None else 0.0),
    )
    return inputs, marker_stability
