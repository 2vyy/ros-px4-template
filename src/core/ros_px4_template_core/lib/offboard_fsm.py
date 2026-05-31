# src/core/ros_px4_template_core/lib/offboard_fsm.py
"""Pure offboard arming/mode state machine — no ROS, no side effects.

Call tick() each control cycle. The caller is responsible for executing
commands that FsmResult.send_arm / send_offboard indicate, and for
updating last_arm_try_s / last_offboard_try_s accordingly.
"""

from __future__ import annotations

from dataclasses import dataclass

# VehicleStatus.NAVIGATION_STATE_OFFBOARD = 14
# Copied here so lib/ remains px4_msgs-free.
_NAV_STATE_OFFBOARD: int = 14


@dataclass(frozen=True)
class FsmInputs:
    elapsed_s: float
    auto_arm: bool
    armed: bool
    arm_failed: bool
    xrce_connected: bool
    xrce_elapsed_s: float
    setpoints_sent: int
    px4_ever_disarmed: bool
    nav_state: int
    arm_delay_s: float
    last_arm_try_s: float
    last_offboard_try_s: float


@dataclass(frozen=True)
class FsmResult:
    state: str  # "IDLE" | "PREARM" | "ARMING" | "ARMED" | "ARM_FAILED"
    send_arm: bool
    send_offboard: bool


def tick(inputs: FsmInputs) -> FsmResult:
    """Compute next state and command flags for one control cycle."""
    if not inputs.auto_arm:
        return FsmResult(
            state="ARMED" if inputs.armed else "IDLE",
            send_arm=False,
            send_offboard=False,
        )

    xrce_ready = (
        inputs.xrce_connected
        and inputs.xrce_elapsed_s >= inputs.arm_delay_s
        and inputs.setpoints_sent > 5
        and inputs.px4_ever_disarmed
    )

    if not xrce_ready:
        return FsmResult(state="PREARM", send_arm=False, send_offboard=False)

    send_offboard = (
        inputs.nav_state != _NAV_STATE_OFFBOARD
        and (inputs.elapsed_s - inputs.last_offboard_try_s) >= 2.0
    )
    send_arm = (
        not inputs.armed
        and not inputs.arm_failed
        and (inputs.elapsed_s - inputs.last_arm_try_s) >= 2.0
    )

    if inputs.armed:
        state = "ARMED"
    elif inputs.arm_failed:
        state = "ARM_FAILED"
    else:
        state = "ARMING"

    return FsmResult(state=state, send_arm=send_arm, send_offboard=send_offboard)
