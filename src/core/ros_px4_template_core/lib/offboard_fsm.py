# src/core/ros_px4_template_core/lib/offboard_fsm.py
"""Pure offboard arming/mode state machine — no ROS, no side effects.

Sequence when auto_arm is enabled:
  PREARM → OFFBOARDING → ARMING → OFFBOARD_TRACK

Position-only: stream setpoints first, switch to OFFBOARD, then arm. Mission
waypoints on ``/drone/target_pose`` drive climb and cruise once OFFBOARD is active.
``offboard_heartbeats_sent`` counts OffboardControlMode publishes, not
TrajectorySetpoint publishes; trajectory setpoints intentionally do not flow
before OFFBOARD (PX4-Autopilot#25273), so do not use them for PREARM readiness.
"""

from __future__ import annotations

from dataclasses import dataclass

# VehicleStatus.NAVIGATION_STATE_OFFBOARD = 14
NAV_STATE_OFFBOARD: int = 14
_NAV_STATE_OFFBOARD: int = NAV_STATE_OFFBOARD


@dataclass(frozen=True)
class FsmInputs:
    elapsed_s: float
    auto_arm: bool
    armed: bool
    arm_failed: bool
    xrce_connected: bool
    xrce_elapsed_s: float
    offboard_heartbeats_sent: int
    px4_ever_disarmed: bool
    nav_state: int
    arm_delay_s: float
    last_arm_try_s: float
    last_offboard_try_s: float


@dataclass(frozen=True)
class FsmResult:
    state: str
    send_arm: bool
    send_offboard: bool


def tick(inputs: FsmInputs) -> FsmResult:
    """Compute next state and command flags for one control cycle."""
    if not inputs.auto_arm:
        if inputs.armed and inputs.nav_state == _NAV_STATE_OFFBOARD:
            return FsmResult(state="OFFBOARD_TRACK", send_arm=False, send_offboard=False)
        return FsmResult(
            state="ARMED" if inputs.armed else "IDLE",
            send_arm=False,
            send_offboard=False,
        )

    xrce_ready = (
        inputs.xrce_connected
        and inputs.xrce_elapsed_s >= inputs.arm_delay_s
        and inputs.offboard_heartbeats_sent > 5
        and inputs.px4_ever_disarmed
    )

    if not xrce_ready:
        return FsmResult(state="PREARM", send_arm=False, send_offboard=False)

    if inputs.arm_failed:
        return FsmResult(state="ARM_FAILED", send_arm=False, send_offboard=False)

    if inputs.nav_state != _NAV_STATE_OFFBOARD:
        send_offboard = (inputs.elapsed_s - inputs.last_offboard_try_s) >= 2.0
        return FsmResult(state="OFFBOARDING", send_arm=False, send_offboard=send_offboard)

    if not inputs.armed:
        send_arm = (inputs.elapsed_s - inputs.last_arm_try_s) >= 2.0
        return FsmResult(state="ARMING", send_arm=send_arm, send_offboard=False)

    return FsmResult(state="OFFBOARD_TRACK", send_arm=False, send_offboard=False)
