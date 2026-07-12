"""Unit tests for the stateful PX4 local-frame tracker."""

from __future__ import annotations

from ros_px4_template_core.lib.frames import enu_setpoint_to_px4_ned
from ros_px4_template_core.lib.px4_local_frame import Px4LocalFrame


def _observe(
    frame: Px4LocalFrame,
    x: float,
    y: float,
    z: float,
    *,
    xy_reset_counter: int = 0,
    delta_x: float = 0.0,
    delta_y: float = 0.0,
    z_reset_counter: int = 0,
    delta_z: float = 0.0,
) -> tuple[float, float, float]:
    """observe() with z_global=True and no-op reset defaults (keeps calls terse)."""
    return frame.observe(
        x,
        y,
        z,
        z_global=True,
        xy_reset_counter=xy_reset_counter,
        delta_x=delta_x,
        delta_y=delta_y,
        z_reset_counter=z_reset_counter,
        delta_z=delta_z,
    )


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
    assert enu == (0.0, 0.0, 0.0)
    assert frame.ready
    assert frame.setpoint_origin_ned == (10.0, 20.0, -2972.0)
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
    assert enu2 == (1.0, 3.0, 3.0)


def test_px4_local_frame_no_reset_sequence_is_stable() -> None:
    # Characterization (plan 051): pin the exact ENU outputs of a multi-sample
    # no-reset sequence. The read-path fix must leave this path byte-identical
    # (all adjusts stay 0.0 when counters never change).
    frame = Px4LocalFrame()
    assert _observe(frame, 0.0, 0.0, -100.0) == (0.0, 0.0, 0.0)
    assert _observe(frame, 2.0, -3.0, -105.0) == (-3.0, 2.0, 5.0)
    assert _observe(frame, 2.5, -3.5, -102.0) == (-3.5, 2.5, 2.0)


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
    assert frame.setpoint_origin_ned == (0.5, -0.5, -2971.75)


def test_read_path_continuous_across_xy_reset() -> None:
    # Anchor, move to B, then the same physical point B re-reported after an xy
    # EKF reset must yield the identical ENU pose (plan 051 core bug).
    frame = Px4LocalFrame()
    _observe(frame, 0.0, 0.0, -5.0)
    enu_b = _observe(frame, 3.0, 4.0, -5.0)
    assert enu_b == (4.0, 3.0, 0.0)
    enu_after = _observe(frame, 3.5, 3.5, -5.0, xy_reset_counter=1, delta_x=0.5, delta_y=-0.5)
    assert enu_after == enu_b  # continuous across the reset (was a 0.5/-0.5 jump before)


def test_read_path_continuous_across_z_reset() -> None:
    frame = Px4LocalFrame()
    _observe(frame, 0.0, 0.0, -5.0)
    enu_b = _observe(frame, 0.0, 0.0, -8.0)
    assert enu_b == (0.0, 0.0, 3.0)
    enu_after = _observe(frame, 0.0, 0.0, -7.5, z_reset_counter=1, delta_z=0.5)
    assert enu_after == enu_b


def test_goto_current_pose_after_reset_commands_no_motion() -> None:
    # End-to-end property the bug violated: after a reset, a GoTo back to the
    # current anchored pose maps (via setpoint_origin_ned) to the exact NED point
    # PX4 currently reports -- hold = zero motion.
    frame = Px4LocalFrame()
    frame.observe(
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
    reported_ned = (10.5, 19.5, -2971.75)  # same physical point after a combined reset
    enu = frame.observe(
        *reported_ned,
        z_global=True,
        xy_reset_counter=1,
        delta_x=0.5,
        delta_y=-0.5,
        z_reset_counter=1,
        delta_z=0.25,
    )
    assert enu == (0.0, 0.0, 0.0)  # pose continuous: still the anchor
    ox, oy, oz = frame.setpoint_origin_ned
    commanded_ned = enu_setpoint_to_px4_ned(*enu, origin_x_ned=ox, origin_y_ned=oy, origin_z_ned=oz)
    assert commanded_ned == reported_ned
