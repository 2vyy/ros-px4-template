"""Unit tests for pure battery telemetry normalization."""

from __future__ import annotations

import math

from ros_px4_template_core.lib.mission.telemetry import usable_battery_remaining


def test_invalid_sentinel_minus_one_is_unusable() -> None:
    assert usable_battery_remaining(connected=True, remaining=-1.0) is None


def test_nan_is_unusable() -> None:
    assert usable_battery_remaining(connected=True, remaining=math.nan) is None


def test_infinity_is_unusable() -> None:
    assert usable_battery_remaining(connected=True, remaining=math.inf) is None
    assert usable_battery_remaining(connected=True, remaining=-math.inf) is None


def test_disconnected_is_unusable_even_with_valid_fraction() -> None:
    assert usable_battery_remaining(connected=False, remaining=0.5) is None


def test_out_of_range_is_unusable() -> None:
    assert usable_battery_remaining(connected=True, remaining=1.5) is None
    assert usable_battery_remaining(connected=True, remaining=-0.1) is None


def test_zero_is_usable() -> None:
    assert usable_battery_remaining(connected=True, remaining=0.0) == 0.0


def test_one_is_usable() -> None:
    assert usable_battery_remaining(connected=True, remaining=1.0) == 1.0


def test_normal_fraction_is_usable() -> None:
    assert usable_battery_remaining(connected=True, remaining=0.42) == 0.42
