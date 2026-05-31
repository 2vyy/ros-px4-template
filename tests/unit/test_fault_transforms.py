# tests/unit/test_fault_transforms.py
"""Unit tests for fault injection transforms (pure functions, no ROS)."""

from __future__ import annotations

import pytest
from ros_px4_template_core.lib.fault_transforms import (
    apply_altitude_spike,
    apply_gps_dropout,
    apply_position_noise,
)


def test_gps_dropout_marks_invalid() -> None:
    valid, valid_z, x, y, z = apply_gps_dropout(xy_valid=True, z_valid=True, x=1.0, y=2.0, z=-3.0)
    assert not valid
    assert not valid_z
    assert x == 1.0  # position unchanged
    assert y == 2.0
    assert z == -3.0


def test_position_noise_shifts_xy() -> None:
    valid, valid_z, x, y, z = apply_position_noise(
        xy_valid=True,
        z_valid=True,
        x=0.0,
        y=0.0,
        z=-5.0,
        sigma_m=2.0,
        rand_x=1.0,
        rand_y=0.0,
    )
    assert valid
    assert valid_z
    assert x == pytest.approx(2.0)  # 0.0 + 1.0 * 2.0
    assert y == pytest.approx(0.0)
    assert z == pytest.approx(-5.0)  # altitude unchanged


def test_position_noise_preserves_validity() -> None:
    valid, valid_z, *_ = apply_position_noise(
        xy_valid=False,
        z_valid=False,
        x=0.0,
        y=0.0,
        z=0.0,
        sigma_m=1.0,
        rand_x=0.0,
        rand_y=0.0,
    )
    assert not valid
    assert not valid_z


def test_altitude_spike_shifts_z() -> None:
    valid, valid_z, x, y, z = apply_altitude_spike(
        xy_valid=True, z_valid=True, x=1.0, y=2.0, z=-3.0, spike_m=5.0
    )
    assert valid
    assert valid_z
    assert x == pytest.approx(1.0)
    assert y == pytest.approx(2.0)
    assert z == pytest.approx(-3.0 + 5.0)


def test_altitude_spike_preserves_xy() -> None:
    _, _, x, y, _ = apply_altitude_spike(
        xy_valid=True, z_valid=True, x=3.0, y=4.0, z=-1.0, spike_m=2.0
    )
    assert x == pytest.approx(3.0)
    assert y == pytest.approx(4.0)
