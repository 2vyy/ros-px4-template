"""Unit tests for the stateful PX4 local-frame tracker."""

from __future__ import annotations

from ros_px4_template_core.lib.px4_local_frame import Px4LocalFrame


def test_px4_local_frame_anchors_xyz_read() -> None:
    frame = Px4LocalFrame()
    enu = frame.observe(
        10.0, 20.0, -2972.0,
        z_global=True, xy_reset_counter=0, delta_x=0.0, delta_y=0.0,
        z_reset_counter=0, delta_z=0.0,
    )
    assert enu == (0.0, 0.0, 0.0)
    assert frame.ready
    assert frame.setpoint_origin_ned == (10.0, 20.0, -2972.0)
    enu2 = frame.observe(
        13.0, 21.0, -2975.0,
        z_global=True, xy_reset_counter=0, delta_x=0.0, delta_y=0.0,
        z_reset_counter=0, delta_z=0.0,
    )
    assert enu2 == (1.0, 3.0, 3.0)


def test_px4_local_frame_accumulates_ekf_reset_into_setpoint_origin() -> None:
    frame = Px4LocalFrame()
    frame.observe(
        0.0, 0.0, -2972.0,
        z_global=True, xy_reset_counter=0, delta_x=0.0, delta_y=0.0,
        z_reset_counter=0, delta_z=0.0,
    )
    frame.observe(
        0.5, -0.5, -2972.25,
        z_global=True, xy_reset_counter=1, delta_x=0.5, delta_y=-0.5,
        z_reset_counter=1, delta_z=0.25,
    )
    assert frame.setpoint_origin_ned == (0.5, -0.5, -2971.75)
