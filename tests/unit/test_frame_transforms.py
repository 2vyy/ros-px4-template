"""Unit tests for frame_transforms (no ROS required)."""

import math

from ros_px4_template_core.lib.frame_transforms import (
    enu_to_ned,
    ned_to_enu,
    quaternion_enu_to_ned,
    quaternion_ned_to_enu,
    velocity_enu_to_ned,
    velocity_ned_to_enu,
    yaw_enu_to_ned,
    yaw_ned_to_enu,
)


def test_ned_to_enu_example() -> None:
    assert ned_to_enu(1.0, 2.0, -3.0) == (2.0, 1.0, 3.0)


def test_enu_to_ned_example() -> None:
    assert enu_to_ned(2.0, 1.0, 3.0) == (1.0, 2.0, -3.0)


def test_round_trip() -> None:
    original = (10.0, -5.0, 2.5)
    assert enu_to_ned(*ned_to_enu(*original)) == original


# --- velocity ---


def test_velocity_ned_to_enu_matches_position() -> None:
    vn, ve, vd = 1.0, 2.0, -3.0
    assert velocity_ned_to_enu(vn, ve, vd) == ned_to_enu(vn, ve, vd)


def test_velocity_enu_to_ned_matches_position() -> None:
    ve, vn, vu = 2.0, 1.0, 3.0
    assert velocity_enu_to_ned(ve, vn, vu) == enu_to_ned(ve, vn, vu)


def test_velocity_round_trip() -> None:
    original = (3.0, -1.5, 0.8)
    assert velocity_enu_to_ned(*velocity_ned_to_enu(*original)) == original


# --- yaw ---


def test_yaw_ned_to_enu_north() -> None:
    assert math.isclose(yaw_ned_to_enu(0.0), math.pi / 2, abs_tol=1e-9)


def test_yaw_ned_to_enu_east() -> None:
    assert math.isclose(yaw_ned_to_enu(math.pi / 2), 0.0, abs_tol=1e-9)


def test_yaw_ned_to_enu_south() -> None:
    assert math.isclose(yaw_ned_to_enu(math.pi), -math.pi / 2, abs_tol=1e-9)


def test_yaw_enu_to_ned_north() -> None:
    assert math.isclose(yaw_enu_to_ned(math.pi / 2), 0.0, abs_tol=1e-9)


def test_yaw_round_trip() -> None:
    for yaw_ned in (0.0, math.pi / 4, math.pi / 2, -math.pi / 2, math.pi):
        recovered = yaw_enu_to_ned(yaw_ned_to_enu(yaw_ned))
        diff = (recovered - yaw_ned + math.pi) % (2 * math.pi) - math.pi
        assert math.isclose(diff, 0.0, abs_tol=1e-9), f"round-trip failed for {yaw_ned}"


# --- quaternion ---

_SQRT2_2 = math.sqrt(2.0) / 2.0


def test_quaternion_identity_ned_facing_north() -> None:
    q = quaternion_ned_to_enu(1.0, 0.0, 0.0, 0.0)
    expected = (0.0, _SQRT2_2, _SQRT2_2, 0.0)
    assert all(math.isclose(a, b, abs_tol=1e-9) for a, b in zip(q, expected, strict=True))


def test_quaternion_ned_to_enu_east() -> None:
    q = quaternion_ned_to_enu(_SQRT2_2, 0.0, 0.0, _SQRT2_2)
    q_back = quaternion_enu_to_ned(*q)
    expected = (_SQRT2_2, 0.0, 0.0, _SQRT2_2)
    assert all(
        math.isclose(a, b, abs_tol=1e-9) for a, b in zip(q_back, expected, strict=True)
    )


def test_quaternion_round_trip() -> None:
    q_ned = (_SQRT2_2, 0.0, 0.0, _SQRT2_2)
    assert all(
        math.isclose(a, b, abs_tol=1e-9)
        for a, b in zip(quaternion_enu_to_ned(*quaternion_ned_to_enu(*q_ned)), q_ned, strict=True)
    )


def test_quaternion_forward_known_value() -> None:
    # NED roll 90° about x_body (North axis): q_ned = (√2/2, √2/2, 0, 0)
    # Expected q_body_enu = Q_NED_TO_ENU ⊗ q_ned = (-0.5, 0.5, 0.5, -0.5)
    q = quaternion_ned_to_enu(_SQRT2_2, _SQRT2_2, 0.0, 0.0)
    expected = (-0.5, 0.5, 0.5, -0.5)
    assert all(math.isclose(a, b, abs_tol=1e-9) for a, b in zip(q, expected, strict=True))
