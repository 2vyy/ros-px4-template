"""Verification harness for the pure frame core (lib/frames.py).

Property-based (hypothesis) invariants plus hand-computed golden sign-trap cases.
Yaw-only by design: roll/pitch are out of scope (see frames.py module docstring).
"""

from __future__ import annotations

import math

from hypothesis import given
from hypothesis import strategies as st
from ros_px4_template_core.lib.frames import (
    body_flu_to_enu_offset,
    camera_to_body,
    drone_pose_from_marker,
    enu_setpoint_to_px4_ned,
    enu_to_ned,
    enu_yaw_from_heading,
    marker_world_from_drone,
    ned_to_enu,
    px4_local_z_ned,
)

_FINITE = st.floats(min_value=-1.0e4, max_value=1.0e4, allow_nan=False, allow_infinity=False)
_YAW = st.floats(min_value=-4.0 * math.pi, max_value=4.0 * math.pi, allow_nan=False)
_NADIR = [[0.0, -1.0, 0.0], [-1.0, 0.0, 0.0], [0.0, 0.0, -1.0]]
_IDENTITY = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]


def _v3() -> st.SearchStrategy[tuple[float, float, float]]:
    return st.tuples(_FINITE, _FINITE, _FINITE)


def _close(a: tuple[float, ...], b: tuple[float, ...], tol: float = 1e-6) -> bool:
    return all(math.isclose(x, y, rel_tol=0.0, abs_tol=tol) for x, y in zip(a, b, strict=True))


# ---- property-based invariants ----


@given(_v3())
def test_ned_enu_roundtrip_identity(v: tuple[float, float, float]) -> None:
    assert _close(enu_to_ned(*ned_to_enu(*v)), v)


@given(_v3())
def test_enu_ned_roundtrip_identity(v: tuple[float, float, float]) -> None:
    assert _close(ned_to_enu(*enu_to_ned(*v)), v)


@given(st.floats(min_value=-100.0, max_value=100.0, allow_nan=False))
def test_enu_yaw_from_heading_in_range(h: float) -> None:
    y = enu_yaw_from_heading(h)
    assert -math.pi - 1e-9 <= y <= math.pi + 1e-9


@given(_FINITE, _FINITE, _YAW)
def test_offset_preserves_horizontal_magnitude(fwd: float, left: float, yaw: float) -> None:
    east, north = body_flu_to_enu_offset((fwd, left, 0.0), yaw)
    assert math.isclose(math.hypot(east, north), math.hypot(fwd, left), rel_tol=1e-9, abs_tol=1e-9)


@given(_v3())
def test_offset_identity_at_yaw_zero(o: tuple[float, float, float]) -> None:
    east, north = body_flu_to_enu_offset(o, 0.0)
    assert math.isclose(east, o[0], abs_tol=1e-9)
    assert math.isclose(north, o[1], abs_tol=1e-9)


@given(_v3(), _v3(), _YAW)
def test_drone_marker_roundtrip(
    drone: tuple[float, float, float], offset: tuple[float, float, float], yaw: float
) -> None:
    marker = marker_world_from_drone(drone, offset, yaw)
    recovered = drone_pose_from_marker(marker, offset, yaw)
    assert _close(recovered, drone, tol=1e-6)


@given(_v3())
def test_setpoint_zero_origin_equals_enu_to_ned(v: tuple[float, float, float]) -> None:
    assert enu_setpoint_to_px4_ned(*v) == enu_to_ned(*v)


@given(_v3())
def test_camera_to_body_identity_extrinsics(t: tuple[float, float, float]) -> None:
    assert _close(camera_to_body(t, _IDENTITY, (0.0, 0.0, 0.0)), t)


@given(_v3())
def test_camera_to_body_preserves_norm(t: tuple[float, float, float]) -> None:
    body = camera_to_body(t, _NADIR, (0.0, 0.0, 0.0))
    assert math.isclose(
        math.dist(body, (0.0, 0.0, 0.0)), math.dist(t, (0.0, 0.0, 0.0)), rel_tol=1e-9, abs_tol=1e-7
    )


# ---- golden example cases (hand-computed) ----


def test_ned_to_enu_example() -> None:
    assert ned_to_enu(1.0, 2.0, -3.0) == (2.0, 1.0, 3.0)


def test_enu_to_ned_example() -> None:
    assert enu_to_ned(2.0, 1.0, 3.0) == (1.0, 2.0, -3.0)


def test_px4_local_z_ned_already_local() -> None:
    z, origin = px4_local_z_ned(-3.0, z_global=False, origin_z_ned=None)
    assert z == -3.0
    assert origin is None


def test_px4_local_z_ned_global_latches_origin() -> None:
    z0, origin = px4_local_z_ned(-2972.0, z_global=True, origin_z_ned=None)
    assert z0 == 0.0
    assert origin == -2972.0
    z1, _ = px4_local_z_ned(-2975.0, z_global=True, origin_z_ned=origin)
    assert z1 == -3.0


def test_enu_setpoint_local() -> None:
    assert enu_setpoint_to_px4_ned(0.0, 0.0, 3.0) == (0.0, 0.0, -3.0)


def test_enu_setpoint_with_origin_and_ekf_adjust() -> None:
    assert enu_setpoint_to_px4_ned(0.0, 0.0, 3.0, origin_z_ned=-2972.0, z_ekf_adjust_ned=0.5) == (
        0.0,
        0.0,
        -2974.5,
    )


def test_enu_setpoint_with_xy_origin() -> None:
    assert enu_setpoint_to_px4_ned(
        5.0, 2.0, 3.0, origin_x_ned=10.0, origin_y_ned=20.0, origin_z_ned=-2972.0
    ) == (12.0, 25.0, -2975.0)


def test_enu_yaw_from_heading_cardinals() -> None:
    assert math.isclose(enu_yaw_from_heading(0.0), math.pi / 2)
    assert math.isclose(enu_yaw_from_heading(math.pi / 2), 0.0)
    assert math.isclose(abs(enu_yaw_from_heading(-math.pi / 2)), math.pi)


def test_camera_to_body_nadir() -> None:
    assert _close(camera_to_body((0.0, 0.0, 5.0), _NADIR, (0.0, 0.0, 0.0)), (0.0, 0.0, -5.0))


def test_forward_localization_marker_world_from_drone() -> None:
    # Drone at (5,0,3) facing North (yaw +90 deg), marker 2 m forward + 3 m down.
    marker = marker_world_from_drone((5.0, 0.0, 3.0), (2.0, 0.0, -3.0), math.pi / 2)
    assert _close(marker, (5.0, 2.0, 0.0))


def test_drone_pose_from_marker_yaw_zero() -> None:
    assert _close(drone_pose_from_marker((8.0, 0.0, 0.0), (8.0, 0.0, -3.0), 0.0), (0.0, 0.0, 3.0))


def test_drone_pose_from_marker_yaw_90() -> None:
    assert _close(
        drone_pose_from_marker((0.0, 5.0, 0.0), (5.0, 0.0, -3.0), math.pi / 2), (0.0, 0.0, 3.0)
    )
