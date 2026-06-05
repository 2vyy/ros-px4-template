"""Single source of truth for vehicle pose.

Reads PX4's estimated VehicleLocalPosition (sim and hardware alike), anchors it
at takeoff, and publishes takeoff-anchored ENU Odometry plus a latched effective
NED setpoint origin. Source is selected by the `source` parameter (topic name
only — the signal is identical):
    sitl    -> /fmu/out/vehicle_local_position_v1
    pixhawk -> /fmu/out/vehicle_local_position

=============================================================================
ROS 2 Interface
Subscriptions: <source topic> [px4_msgs/VehicleLocalPosition]
Publishers:
    /drone/odom          [nav_msgs/Odometry]            anchored ENU pose+yaw+twist
    /drone/local_origin  [geometry_msgs/Vector3Stamped] effective NED setpoint origin
=============================================================================
"""

from __future__ import annotations

import math

import rclpy
from geometry_msgs.msg import Vector3Stamped
from nav_msgs.msg import Odometry
from px4_msgs.msg import VehicleLocalPosition
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy

from ros_px4_template_core.lib.frame_transforms import (
    Px4LocalFrame,
    enu_yaw_from_heading,
    ned_to_enu,
)
from ros_px4_template_core.lib.structured_logger import StructuredLogger

_SOURCE_TOPICS = {
    "sitl": "/fmu/out/vehicle_local_position_v1",
    "pixhawk": "/fmu/out/vehicle_local_position",
}

_PX4_QOS = QoSProfile(
    reliability=ReliabilityPolicy.BEST_EFFORT,
    durability=DurabilityPolicy.TRANSIENT_LOCAL,
    history=HistoryPolicy.KEEP_LAST,
    depth=10,
)
_ODOM_QOS = QoSProfile(
    reliability=ReliabilityPolicy.RELIABLE,
    durability=DurabilityPolicy.VOLATILE,
    history=HistoryPolicy.KEEP_LAST,
    depth=10,
)
_LATCHED_QOS = QoSProfile(
    reliability=ReliabilityPolicy.RELIABLE,
    durability=DurabilityPolicy.TRANSIENT_LOCAL,
    history=HistoryPolicy.KEEP_LAST,
    depth=1,
)


class PositionNode(Node):
    """Anchored-ENU single source of truth from PX4's local-position estimate."""

    def __init__(self) -> None:
        super().__init__("position_node")
        self.declare_parameter("source", "sitl")
        self.declare_parameter("frame_id", "map")
        self.declare_parameter("child_frame_id", "base_link")
        self.declare_parameter("log_dir", "./logs")

        source = str(self.get_parameter("source").value)
        if source not in _SOURCE_TOPICS:
            raise RuntimeError(
                f"position_node: invalid source '{source}'; expected one of {list(_SOURCE_TOPICS)}"
            )
        self._topic = _SOURCE_TOPICS[source]
        self._frame_id = str(self.get_parameter("frame_id").value)
        self._child_frame_id = str(self.get_parameter("child_frame_id").value)
        self.slog = StructuredLogger(self, log_dir=str(self.get_parameter("log_dir").value))

        self._frame = Px4LocalFrame()
        self._have_pose = False

        self.create_subscription(VehicleLocalPosition, self._topic, self._position_cb, _PX4_QOS)
        self._pub_odom = self.create_publisher(Odometry, "/drone/odom", _ODOM_QOS)
        self._pub_origin = self.create_publisher(
            Vector3Stamped, "/drone/local_origin", _LATCHED_QOS
        )
        self.slog.info("position_node ready", source=source, topic=self._topic)

    def _position_cb(self, msg: VehicleLocalPosition) -> None:
        if not (msg.xy_valid and msg.z_valid):
            return
        x_enu, y_enu, z_enu = self._frame.observe(
            float(msg.x),
            float(msg.y),
            float(msg.z),
            z_global=bool(msg.z_global),
            xy_reset_counter=int(msg.xy_reset_counter),
            delta_x=float(msg.delta_xy[0]),
            delta_y=float(msg.delta_xy[1]),
            z_reset_counter=int(msg.z_reset_counter),
            delta_z=float(msg.delta_z),
        )
        yaw_enu = enu_yaw_from_heading(float(msg.heading))
        stamp = self.get_clock().now().to_msg()

        odom = Odometry()
        odom.header.stamp = stamp
        odom.header.frame_id = self._frame_id
        odom.child_frame_id = self._child_frame_id
        odom.pose.pose.position.x = x_enu
        odom.pose.pose.position.y = y_enu
        odom.pose.pose.position.z = z_enu
        odom.pose.pose.orientation.z = math.sin(yaw_enu / 2.0)
        odom.pose.pose.orientation.w = math.cos(yaw_enu / 2.0)
        # PX4 velocity is NED; ned_to_enu maps it to ENU (vx_enu=ve, vy_enu=vn, vz_enu=-vd).
        vx_enu, vy_enu, vz_enu = ned_to_enu(float(msg.vx), float(msg.vy), float(msg.vz))
        odom.twist.twist.linear.x = vx_enu
        odom.twist.twist.linear.y = vy_enu
        odom.twist.twist.linear.z = vz_enu
        self._pub_odom.publish(odom)

        ox, oy, oz = self._frame.setpoint_origin_ned
        origin = Vector3Stamped()
        origin.header.stamp = stamp
        origin.header.frame_id = self._frame_id
        origin.vector.x = ox
        origin.vector.y = oy
        origin.vector.z = oz
        self._pub_origin.publish(origin)

        if not self._have_pose:
            self._have_pose = True
            self.slog.info("First pose published", x=x_enu, y=y_enu, z=z_enu)

    def destroy_node(self) -> None:
        self.slog.close()
        super().destroy_node()


def main(args: list[str] | None = None) -> None:
    rclpy.init(args=args)
    node = PositionNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
