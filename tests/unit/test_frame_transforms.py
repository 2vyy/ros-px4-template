"""Unit tests for frame_transforms (no ROS required)."""

from ros_px4_template_core.lib.frame_transforms import (
    Px4ZFrameTracker,
    enu_setpoint_to_px4_ned,
    enu_to_ned,
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


def test_px4_z_frame_tracker_accumulates_ekf_delta() -> None:
    tracker = Px4ZFrameTracker()
    z0 = tracker.observe(-2972.0, z_global=True, z_reset_counter=0, delta_z=0.0)
    assert z0 == 0.0
    assert tracker.home_z_ned == -2972.0
    z1 = tracker.observe(-2975.0, z_global=True, z_reset_counter=1, delta_z=0.25)
    assert z1 == -3.0
    assert tracker.setpoint_z_adjust_ned == 0.25
