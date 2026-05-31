# tests/unit/test_offboard_fsm.py
"""Unit tests for the pure offboard arming state machine."""

from __future__ import annotations

from ros_px4_template_core.lib.offboard_fsm import FsmInputs, tick

# A fully-ready set of inputs — all preconditions for arming met.
_READY: dict[str, object] = dict(
    elapsed_s=30.0,
    auto_arm=True,
    armed=False,
    arm_failed=False,
    xrce_connected=True,
    xrce_elapsed_s=15.0,
    setpoints_sent=10,
    px4_ever_disarmed=True,
    nav_state=0,
    arm_delay_s=10.0,
    last_arm_try_s=0.0,
    last_offboard_try_s=0.0,
)


def _inputs(**overrides: object) -> FsmInputs:
    return FsmInputs(**{**_READY, **overrides})


def test_idle_when_manual_and_disarmed() -> None:
    result = tick(_inputs(auto_arm=False, armed=False))
    assert result.state == "IDLE"
    assert not result.send_arm
    assert not result.send_offboard


def test_armed_when_manual_and_armed() -> None:
    result = tick(_inputs(auto_arm=False, armed=True))
    assert result.state == "ARMED"


def test_prearm_when_xrce_not_connected() -> None:
    result = tick(_inputs(xrce_connected=False))
    assert result.state == "PREARM"
    assert not result.send_arm
    assert not result.send_offboard


def test_prearm_when_xrce_delay_not_elapsed() -> None:
    result = tick(_inputs(xrce_elapsed_s=5.0, arm_delay_s=10.0))
    assert result.state == "PREARM"


def test_prearm_when_too_few_setpoints() -> None:
    result = tick(_inputs(setpoints_sent=3))
    assert result.state == "PREARM"


def test_prearm_when_px4_never_disarmed() -> None:
    result = tick(_inputs(px4_ever_disarmed=False))
    assert result.state == "PREARM"


def test_arming_state_when_ready_and_not_armed() -> None:
    # nav_state=14 → already in OFFBOARD, so no offboard send; still ARMING
    result = tick(_inputs(nav_state=14))
    assert result.state == "ARMING"


def test_sends_offboard_when_not_in_offboard_mode() -> None:
    result = tick(_inputs(nav_state=0, last_offboard_try_s=0.0, elapsed_s=30.0))
    assert result.send_offboard


def test_no_offboard_if_recently_sent() -> None:
    # last sent 0.5 s ago — threshold is 2.0 s
    result = tick(_inputs(nav_state=0, last_offboard_try_s=29.5, elapsed_s=30.0))
    assert not result.send_offboard


def test_no_offboard_when_already_in_offboard_mode() -> None:
    result = tick(_inputs(nav_state=14))
    assert not result.send_offboard


def test_sends_arm_command_when_ready() -> None:
    result = tick(_inputs(armed=False, arm_failed=False, last_arm_try_s=0.0, elapsed_s=30.0))
    assert result.send_arm


def test_no_arm_if_recently_tried() -> None:
    result = tick(_inputs(last_arm_try_s=29.5, elapsed_s=30.0))
    assert not result.send_arm


def test_arm_failed_state() -> None:
    result = tick(_inputs(arm_failed=True))
    assert result.state == "ARM_FAILED"
    assert not result.send_arm


def test_armed_state_when_armed() -> None:
    result = tick(_inputs(armed=True))
    assert result.state == "ARMED"
    assert not result.send_arm
