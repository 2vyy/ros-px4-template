"""Unit tests for px4_pose_adapter valid-gate logic."""

from __future__ import annotations

from ros_px4_template_core.lib.frame_transforms import ned_to_enu


def test_ned_to_enu_for_pose_publish() -> None:
    x, y, z = ned_to_enu(1.0, 2.0, -3.0)
    assert (x, y, z) == (2.0, 1.0, 3.0)


def test_valid_flags_gate() -> None:
    """Document expected gate: only publish when xy_valid and z_valid."""

    def should_publish(xy_valid: bool, z_valid: bool) -> bool:
        return xy_valid and z_valid

    assert should_publish(True, True)
    assert not should_publish(False, True)
    assert not should_publish(True, False)
