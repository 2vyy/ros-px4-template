"""Characterization tests for the offboard safety latches (plan 057).

Pins today's semantics of the disarm/landing/failsafe latches exactly, quirks
included -- a falling failsafe edge does NOT clear the latch.
"""

from __future__ import annotations

from ros_px4_template_core.lib import events
from ros_px4_template_core.lib.offboard_latches import (
    PX4_DISARMED_OBSERVED,
    RESULT_FAILED,
    RESULT_UNSUPPORTED,
    Latches,
    on_arm_ack,
    on_land_command,
    on_vehicle_status,
    try_clear_auto_arm,
)


def test_armed_to_disarmed_latches_disarm_once() -> None:
    latches = Latches(armed=True)
    ev = on_vehicle_status(latches, armed=False, failsafe=False, disarmed=True, preflight_ok=False)
    assert latches.disarm_latched
    assert events.AUTO_ARM_DISABLED_ON_DISARM in ev
    # disarmed -> disarmed: no edge, no repeat event
    ev2 = on_vehicle_status(latches, armed=False, failsafe=False, disarmed=True, preflight_ok=False)
    assert events.AUTO_ARM_DISABLED_ON_DISARM not in ev2
    assert latches.disarm_latched


def test_failsafe_rising_latches_falling_edge_does_not_clear() -> None:
    latches = Latches()
    ev = on_vehicle_status(latches, armed=False, failsafe=True, disarmed=False, preflight_ok=False)
    assert latches.failsafe_latched
    assert latches.failsafe_active
    assert events.FAILSAFE_MODE_COMMANDS_LATCHED in ev
    ev2 = on_vehicle_status(
        latches, armed=False, failsafe=False, disarmed=False, preflight_ok=False
    )
    assert not latches.failsafe_active
    assert latches.failsafe_latched  # the quirk: falling edge does NOT clear the latch
    assert events.FAILSAFE_CLEARED_LIVE in ev2


def test_px4_ever_disarmed_requires_preflight_ok() -> None:
    latches = Latches()
    on_vehicle_status(latches, armed=False, failsafe=False, disarmed=True, preflight_ok=False)
    assert not latches.px4_ever_disarmed
    ev = on_vehicle_status(latches, armed=False, failsafe=False, disarmed=True, preflight_ok=True)
    assert latches.px4_ever_disarmed
    assert PX4_DISARMED_OBSERVED in ev


def test_clear_rejected_while_failsafe_active() -> None:
    latches = Latches(failsafe_active=True, failsafe_latched=True, disarm_latched=True)
    ok, reason, evs = try_clear_auto_arm(latches)
    assert not ok
    assert "failsafe" in reason
    assert latches.failsafe_latched  # nothing cleared
    assert latches.disarm_latched
    assert evs == [(events.FAILSAFE_LATCH_CLEAR_REJECTED, {})]


def test_clear_rejected_while_landing_handoff_active() -> None:
    latches = Latches(landing=True, armed=True, landing_latched=True)
    ok, reason, evs = try_clear_auto_arm(latches)
    assert not ok
    assert "landing" in reason
    assert latches.landing_latched
    assert evs == [(events.LANDING_LATCH_CLEAR_REJECTED, {})]


def test_clear_after_touchdown_clears_landing_flag_and_latch() -> None:
    latches = Latches(landing=True, armed=False, landing_latched=True)
    ok, _reason, evs = try_clear_auto_arm(latches)
    assert ok
    assert not latches.landing_latched
    assert not latches.landing
    assert (events.AUTO_ARM_LATCH_CLEARED_BY_PARAM, {"latch": "landing"}) in evs


def test_clear_all_three_latches_emits_three_events_in_order() -> None:
    latches = Latches(disarm_latched=True, failsafe_latched=True, landing_latched=True)
    ok, _reason, evs = try_clear_auto_arm(latches)
    assert ok
    assert not latches.disarm_latched
    assert not latches.failsafe_latched
    assert not latches.landing_latched
    assert [kw["latch"] for _name, kw in evs] == ["disarm", "failsafe", "landing"]


def test_arm_ack_terminal_result_latches_once() -> None:
    latches = Latches()
    assert on_arm_ack(latches, RESULT_FAILED, "FAILED") is True
    assert latches.arm_failed
    assert latches.arm_fail_reason == "FAILED"
    # a second terminal ack does not re-fire or overwrite the reason
    assert on_arm_ack(latches, RESULT_UNSUPPORTED, "UNSUPPORTED") is False
    assert latches.arm_fail_reason == "FAILED"


def test_arm_ack_non_terminal_result_not_latched() -> None:
    latches = Latches()
    assert on_arm_ack(latches, 2, "DENIED") is False  # DENIED
    assert on_arm_ack(latches, 1, "TEMPORARILY_REJECTED") is False
    assert not latches.arm_failed


def test_land_command_is_idempotent() -> None:
    latches = Latches()
    assert on_land_command(latches) is True
    assert latches.landing
    assert latches.landing_latched
    assert on_land_command(latches) is False  # already landing: no second NAV_LAND
