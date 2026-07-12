"""Pure offboard safety-latch transitions -- no ROS, no side effects.

The three latches that stop ``offboard_controller`` from fighting PX4's own
failsafe/lander -- disarm (plan 030), landing (plan 042), failsafe (plan 044) --
plus the terminal arm-failure flag and the ``px4_ever_disarmed`` readiness gate.
Each function mutates a :class:`Latches` and returns what the node must emit or
do, so the node callbacks become "unpack msg -> call pure fn -> publish/slog".

This is characterization: the semantics reproduce the node exactly, quirks
included -- notably a FALLING failsafe edge logs ``FAILSAFE_CLEARED_LIVE`` but
does NOT clear ``failsafe_latched`` (only an explicit ``auto_arm=true`` clears
latches, via :func:`try_clear_auto_arm`).
"""

from __future__ import annotations

from dataclasses import dataclass

from ros_px4_template_core.lib import events

# VehicleCommandAck.VEHICLE_CMD_RESULT_* (px4_msgs); duplicated here to keep this
# module rclpy/px4_msgs-free, matching the lib/ purity rule.
RESULT_UNSUPPORTED = 3
RESULT_FAILED = 4

# String literal the node logs directly (not in lib/events.py).
PX4_DISARMED_OBSERVED = "PX4_DISARMED_OBSERVED"


@dataclass
class Latches:
    armed: bool = False
    disarm_latched: bool = False
    failsafe_active: bool = False
    failsafe_latched: bool = False
    landing: bool = False
    landing_latched: bool = False
    arm_failed: bool = False
    arm_fail_reason: str = ""
    px4_ever_disarmed: bool = False


def on_vehicle_status(
    latches: Latches, *, armed: bool, failsafe: bool, disarmed: bool, preflight_ok: bool
) -> list[str]:
    """Apply a VehicleStatus update; return event names to log, in order."""
    out: list[str] = []
    was_armed = latches.armed
    latches.armed = armed
    if was_armed and not latches.armed:
        latches.disarm_latched = True
        out.append(events.AUTO_ARM_DISABLED_ON_DISARM)
    was_failsafe = latches.failsafe_active
    latches.failsafe_active = failsafe
    if latches.failsafe_active and not was_failsafe:
        latches.failsafe_latched = True
        out.append(events.FAILSAFE_MODE_COMMANDS_LATCHED)
    elif not latches.failsafe_active and was_failsafe:
        out.append(events.FAILSAFE_CLEARED_LIVE)
    if not latches.px4_ever_disarmed and disarmed and preflight_ok:
        latches.px4_ever_disarmed = True
        out.append(PX4_DISARMED_OBSERVED)
    return out


def on_land_command(latches: Latches) -> bool:
    """Latch the landing hand-off. Returns True when NAV_LAND must be sent now
    (idempotent: a second call while already landing returns False, no mutation)."""
    if latches.landing:
        return False
    latches.landing = True
    latches.landing_latched = True
    return True


def on_arm_ack(latches: Latches, result: int, reason: str) -> bool:
    """Apply an ARM_DISARM ack. Returns True only on the FIRST terminal
    (UNSUPPORTED/FAILED) result, when ``arm_failed`` is newly promoted."""
    if result in (RESULT_UNSUPPORTED, RESULT_FAILED) and not latches.arm_failed:
        latches.arm_failed = True
        latches.arm_fail_reason = reason
        return True
    return False


def try_clear_auto_arm(latches: Latches) -> tuple[bool, str, list[tuple[str, dict]]]:
    """Handle an ``auto_arm=true`` param set. Returns ``(ok, reject_reason,
    events)`` where each event is ``(name, kwargs)``. Rejected (no clearing)
    while a failsafe is active, or while a landing hand-off is active
    (``landing and armed``); otherwise clears whichever latches are set."""
    if latches.failsafe_active:
        return (
            False,
            "cannot clear latches while PX4 failsafe is active",
            [(events.FAILSAFE_LATCH_CLEAR_REJECTED, {})],
        )
    if latches.landing and latches.armed:
        return (
            False,
            "cannot clear landing latch while landing hand-off is active",
            [(events.LANDING_LATCH_CLEAR_REJECTED, {})],
        )
    out: list[tuple[str, dict]] = []
    if latches.disarm_latched:
        latches.disarm_latched = False
        out.append((events.AUTO_ARM_LATCH_CLEARED_BY_PARAM, {"latch": "disarm"}))
    if latches.failsafe_latched:
        latches.failsafe_latched = False
        out.append((events.AUTO_ARM_LATCH_CLEARED_BY_PARAM, {"latch": "failsafe"}))
    if latches.landing_latched:
        latches.landing_latched = False
        latches.landing = False
        out.append((events.AUTO_ARM_LATCH_CLEARED_BY_PARAM, {"latch": "landing"}))
    return (True, "", out)
