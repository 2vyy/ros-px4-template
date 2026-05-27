"""Unit tests for frame_transforms (no ROS required)."""

from ros_px4_template_core.lib.frame_transforms import enu_to_ned, ned_to_enu


def test_ned_to_enu_example() -> None:
    assert ned_to_enu(1.0, 2.0, -3.0) == (2.0, 1.0, 3.0)


def test_enu_to_ned_example() -> None:
    assert enu_to_ned(2.0, 1.0, 3.0) == (1.0, 2.0, -3.0)


def test_round_trip() -> None:
    original = (10.0, -5.0, 2.5)
    assert enu_to_ned(*ned_to_enu(*original)) == original
