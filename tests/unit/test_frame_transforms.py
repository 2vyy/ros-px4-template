"""Unit tests for frame_transforms (no ROS required)."""

import math

from ros_px4_template_core.lib.frame_transforms import (
    Px4LocalFrame,
    enu_setpoint_to_px4_ned,
    enu_to_ned,
    enu_yaw_from_heading,
    ned_to_enu,
    px4_local_z_ned,
)


def test_ned_to_enu_example() -> None:
    assert ned_to_enu(1.0, 2.0, -3.0) == (2.0, 1.0, 3.0)


def test_enu_to_ned_example() -> None:
    assert enu_to_ned(2.0, 1.0, 3.0) == (1.0, 2.0, -3.0)


def test_round_trip() -> None:
    original = (10.0, -5.0, 2.5)
    assert enu_to_ned(*ned_to_enu(*original)) == original


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


def test_enu_setpoint_to_px4_ned_local() -> None:
    x, y, z = enu_setpoint_to_px4_ned(0.0, 0.0, 3.0)
    assert (x, y, z) == (0.0, 0.0, -3.0)


def test_enu_setpoint_to_px4_ned_with_origin_and_ekf_adjust() -> None:
    x, y, z = enu_setpoint_to_px4_ned(
        0.0,
        0.0,
        3.0,
        origin_z_ned=-2972.0,
        z_ekf_adjust_ned=0.5,
    )
    assert (x, y, z) == (0.0, 0.0, -2974.5)


def test_enu_yaw_from_heading_cardinals() -> None:
    # PX4 heading: 0 = North. ENU yaw: 0 = East, pi/2 = North.
    assert math.isclose(enu_yaw_from_heading(0.0), math.pi / 2)  # North
    assert math.isclose(enu_yaw_from_heading(math.pi / 2), 0.0)  # East
    # Facing West (heading = -pi/2) -> ENU yaw = pi
    assert math.isclose(abs(enu_yaw_from_heading(-math.pi / 2)), math.pi)


def test_enu_setpoint_to_px4_ned_with_xy_origin() -> None:
    # Target 5 East, 2 North, 3 Up, with NED origin (10 N, 20 E, -2972 D).
    x, y, z = enu_setpoint_to_px4_ned(
        5.0,
        2.0,
        3.0,
        origin_x_ned=10.0,
        origin_y_ned=20.0,
        origin_z_ned=-2972.0,
    )
    # enu_to_ned(5,2,3) = (2, 5, -3); add origin.
    assert (x, y, z) == (12.0, 25.0, -2975.0)


def test_px4_local_frame_anchors_xyz_read() -> None:
    frame = Px4LocalFrame()
    enu = frame.observe(
        10.0,
        20.0,
        -2972.0,
        z_global=True,
        xy_reset_counter=0,
        delta_x=0.0,
        delta_y=0.0,
        z_reset_counter=0,
        delta_z=0.0,
    )
    assert enu == (0.0, 0.0, 0.0)  # starts at origin (anchored ENU)
    assert frame.ready
    assert frame.setpoint_origin_ned == (10.0, 20.0, -2972.0)
    # Move 3 N, 1 E, climb to 3 m up (z -> -2975 down).
    enu2 = frame.observe(
        13.0,
        21.0,
        -2975.0,
        z_global=True,
        xy_reset_counter=0,
        delta_x=0.0,
        delta_y=0.0,
        z_reset_counter=0,
        delta_z=0.0,
    )
    # local NED (3 N, 1 E, -3 D) -> ENU (1 E, 3 N, 3 U)
    assert enu2 == (1.0, 3.0, 3.0)


def test_px4_local_frame_accumulates_ekf_reset_into_setpoint_origin() -> None:
    frame = Px4LocalFrame()
    frame.observe(
        0.0,
        0.0,
        -2972.0,
        z_global=True,
        xy_reset_counter=0,
        delta_x=0.0,
        delta_y=0.0,
        z_reset_counter=0,
        delta_z=0.0,
    )
    frame.observe(
        0.5,
        -0.5,
        -2972.25,
        z_global=True,
        xy_reset_counter=1,
        delta_x=0.5,
        delta_y=-0.5,
        z_reset_counter=1,
        delta_z=0.25,
    )
    # Setpoint origin absorbs the reset deltas so commands keep their target.
    assert frame.setpoint_origin_ned == (0.5, -0.5, -2971.75)
