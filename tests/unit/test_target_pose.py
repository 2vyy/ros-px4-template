"""Unit tests for the pure optional-yaw quaternion codec (lib/target_pose.py).

No ROS imports here or in the module under test: this is the pure boundary
between mission-yaw-as-radians and the geometry_msgs quaternion sentinel.
"""

from __future__ import annotations

import math

from ros_px4_template_core.lib.frames import enu_quaternion_from_yaw
from ros_px4_template_core.lib.target_pose import (
    target_yaw_from_quaternion,
    target_yaw_to_quaternion,
)


def test_to_quaternion_none_is_all_zero_sentinel() -> None:
    assert target_yaw_to_quaternion(None) == (0.0, 0.0, 0.0, 0.0)


def test_to_quaternion_delegates_to_enu_quaternion_from_yaw() -> None:
    yaw = math.pi / 3
    assert target_yaw_to_quaternion(yaw) == enu_quaternion_from_yaw(yaw)


def test_from_quaternion_all_zero_is_none() -> None:
    assert target_yaw_from_quaternion(0.0, 0.0, 0.0, 0.0) is None


def test_roundtrip_sentinel() -> None:
    q = target_yaw_to_quaternion(None)
    assert target_yaw_from_quaternion(*q) is None


def test_roundtrip_cardinal_yaws() -> None:
    for yaw in (0.0, math.pi / 2, math.pi, -math.pi / 2, -math.pi):
        q = target_yaw_to_quaternion(yaw)
        recovered = target_yaw_from_quaternion(*q)
        assert recovered is not None
        assert math.isclose(math.sin(recovered), math.sin(yaw), abs_tol=1e-9)
        assert math.isclose(math.cos(recovered), math.cos(yaw), abs_tol=1e-9)


def test_slightly_non_unit_quaternion_still_decodes() -> None:
    w, x, y, z = enu_quaternion_from_yaw(math.pi / 4)
    scale = 1.01
    recovered = target_yaw_from_quaternion(w * scale, x * scale, y * scale, z * scale)
    assert recovered is not None
    assert math.isclose(recovered, math.pi / 4, abs_tol=1e-3)


def test_nan_component_is_none() -> None:
    assert target_yaw_from_quaternion(float("nan"), 0.0, 0.0, 0.0) is None


def test_infinite_component_is_none() -> None:
    assert target_yaw_from_quaternion(float("inf"), 0.0, 0.0, 0.0) is None


def test_non_zero_malformed_quaternion_is_none() -> None:
    # Non-zero but grossly non-unit norm — malformed, not a real orientation.
    assert target_yaw_from_quaternion(5.0, 5.0, 5.0, 5.0) is None
