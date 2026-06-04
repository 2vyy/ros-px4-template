"""Unit tests for setpoint_hold (B23)."""

from __future__ import annotations

from ros_px4_template_core.lib.setpoint_hold import (
    effective_target_setpoint,
    is_target_pose_stale,
    px4_trajectory_setpoint_enu,
)


def test_no_target_yet_holds_current() -> None:
    assert effective_target_setpoint((0, 0, 3), (1, 2, 3), None) == (1, 2, 3)


def test_fresh_command_used() -> None:
    assert effective_target_setpoint((5, 0, 3), (1, 2, 3), 99.0) == (5, 0, 3)


def test_stale_command_holds_commanded_not_current() -> None:
    """Stale must not ratchet setpoint Z to current altitude during climb."""
    assert effective_target_setpoint((5, 0, 3), (1, 2, 8), 90.0) == (5, 0, 3)


def test_is_target_pose_stale() -> None:
    assert not is_target_pose_stale(None, 100.0, 2.0)
    assert not is_target_pose_stale(99.0, 100.0, 2.0)
    assert is_target_pose_stale(90.0, 100.0, 2.0)


def test_px4_setpoint_holds_current_until_offboard() -> None:
    assert px4_trajectory_setpoint_enu((0, 0, 3), (1, 2, 0.1), offboard_active=False) == (
        1,
        2,
        0.1,
    )


def test_px4_setpoint_uses_mission_when_offboard() -> None:
    assert px4_trajectory_setpoint_enu((0, 0, 3), (1, 2, 0.1), offboard_active=True) == (
        0,
        0,
        3,
    )
