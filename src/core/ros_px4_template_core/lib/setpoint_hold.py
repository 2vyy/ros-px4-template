"""Setpoint hold helpers for offboard_controller."""

from __future__ import annotations


def is_target_pose_stale(
    last_command_time: float | None,
    now: float,
    timeout_s: float,
) -> bool:
    """True when a command was received but the stream has gone quiet."""
    if last_command_time is None:
        return False
    return now - last_command_time > timeout_s


def effective_target_setpoint(
    commanded_enu: tuple[float, float, float],
    current_enu: tuple[float, float, float],
    last_command_time: float | None,
) -> tuple[float, float, float]:
    """Return the active position setpoint in ENU.

    When *last_command_time* is None (no ``/drone/target_pose`` yet), hold at
    *current_enu* instead of flying toward the boot-time default (0, 0, target_alt).

    After the first command, always use *commanded_enu* even if the stream goes stale.
    """
    if last_command_time is None:
        return current_enu
    return commanded_enu


def px4_trajectory_setpoint_enu(
    mission_enu: tuple[float, float, float],
    current_enu: tuple[float, float, float],
    *,
    offboard_active: bool,
) -> tuple[float, float, float]:
    """Return the ENU setpoint to stream on ``/fmu/in/trajectory_setpoint``.

    uXRCE-DDS applies setpoints before offboard mode is active. Until
    NAV_STATE_OFFBOARD, hold current pose so PX4 is not given a climb target early.
    """
    if offboard_active:
        return mission_enu
    return current_enu
