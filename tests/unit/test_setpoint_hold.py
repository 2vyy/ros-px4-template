"""Unit tests for setpoint_hold (B23)."""

from __future__ import annotations

from ros_px4_template_core.lib.setpoint_hold import effective_target_setpoint


def test_no_target_yet_holds_current() -> None:
    assert effective_target_setpoint((0, 0, 3), (1, 2, 3), None, 100.0, 2.0) == (1, 2, 3)


def test_fresh_command_used() -> None:
    assert effective_target_setpoint((5, 0, 3), (1, 2, 3), 99.0, 100.0, 2.0) == (5, 0, 3)


def test_stale_command_holds_current() -> None:
    assert effective_target_setpoint((5, 0, 3), (1, 2, 3), 90.0, 100.0, 2.0) == (1, 2, 3)
