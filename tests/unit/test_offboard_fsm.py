# tests/unit/test_offboard_fsm.py
"""Unit tests for the pure offboard arming state machine."""

from __future__ import annotations

from typing import Any

from ros_px4_template_core.lib.offboard_fsm import FsmInputs, tick

_READY: dict[str, Any] = dict(
    elapsed_s=30.0,
    auto_arm=True,
    armed=False,
    arm_failed=False,
    xrce_connected=True,
    xrce_elapsed_s=15.0,
    offboard_heartbeats_sent=10,
    px4_ever_disarmed=True,
    nav_state=4,
    arm_delay_s=10.0,
    last_arm_try_s=0.0,
    last_offboard_try_s=0.0,
)


def _inputs(**overrides: Any) -> FsmInputs:
    return FsmInputs(**{**_READY, **overrides})


def test_idle_when_manual_and_disarmed() -> None:
    result = tick(_inputs(auto_arm=False, armed=False))
    assert result.state == "IDLE"
    assert not result.send_arm
    assert not result.send_offboard


def test_offboard_track_when_manual_armed_in_offboard() -> None:
    result = tick(_inputs(auto_arm=False, armed=True, nav_state=14))
    assert result.state == "OFFBOARD_TRACK"


def test_prearm_when_xrce_not_ready() -> None:
    result = tick(_inputs(xrce_connected=False))
    assert result.state == "PREARM"
    assert not result.send_arm


def test_offboarding_before_arm() -> None:
    result = tick(_inputs(armed=False, nav_state=4, last_offboard_try_s=0.0))
    assert result.state == "OFFBOARDING"
    assert result.send_offboard
    assert not result.send_arm


def test_arming_after_offboard() -> None:
    result = tick(_inputs(armed=False, nav_state=14, last_arm_try_s=0.0))
    assert result.state == "ARMING"
    assert result.send_arm
    assert not result.send_offboard


def test_offboard_track_when_armed_in_offboard() -> None:
    result = tick(_inputs(armed=True, nav_state=14))
    assert result.state == "OFFBOARD_TRACK"
    assert not result.send_offboard
    assert not result.send_arm


def test_arm_failed_state() -> None:
    result = tick(_inputs(arm_failed=True))
    assert result.state == "ARM_FAILED"
    assert not result.send_arm
