"""Publish canonical ENU pose from PX4 local position (hardware default backend).

=============================================================================
ROS 2 Interface
=============================================================================

Subscriptions:
    /fmu/out/vehicle_local_position  [px4_msgs/VehicleLocalPosition]

Publishers:
    /drone/pose_enu  [geometry_msgs/PoseStamped]
=============================================================================
"""

from __future__ import annotations

import rclpy
from geometry_msgs.msg import PoseStamped
from px4_msgs.msg import VehicleLocalPosition
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy

from ros_px4_template_core.lib.frame_transforms import ned_to_enu
from ros_px4_template_core.lib.structured_logger import StructuredLogger

POSE_ENU_TOPIC = "/drone/pose_enu"

_PX4_QOS = QoSProfile(
    reliability=ReliabilityPolicy.BEST_EFFORT,
    durability=DurabilityPolicy.TRANSIENT_LOCAL,
    history=HistoryPolicy.KEEP_LAST,
    depth=10,
)
_POSE_QOS = QoSProfile(
    reliability=ReliabilityPolicy.RELIABLE,
    durability=DurabilityPolicy.VOLATILE,
    history=HistoryPolicy.KEEP_LAST,
    depth=10,
)


class Px4PoseAdapter(Node):
    """Republish PX4 NED local position as ENU PoseStamped on /drone/pose_enu."""

    def __init__(self) -> None:
        super().__init__("px4_pose_adapter")
        self.declare_parameter("log_dir", "./logs")
        self.declare_parameter("frame_id", "map")
        log_dir = str(self.get_parameter("log_dir").value)
        self._frame_id = str(self.get_parameter("frame_id").value)
        self.slog = StructuredLogger(self, log_dir=log_dir)
        self._have_pose = False
        self.create_subscription(
            VehicleLocalPosition,
            "/fmu/out/vehicle_local_position",
            self._position_cb,
            _PX4_QOS,
        )
        self._pub = self.create_publisher(PoseStamped, POSE_ENU_TOPIC, _POSE_QOS)
        self.slog.info("Px4PoseAdapter ready", frame_id=self._frame_id)

    def _position_cb(self, msg: VehicleLocalPosition) -> None:
        if not (msg.xy_valid and msg.z_valid):
            return
        x, y, z = ned_to_enu(msg.x, msg.y, msg.z)
        out = PoseStamped()
        out.header.stamp = self.get_clock().now().to_msg()
        out.header.frame_id = self._frame_id
        out.pose.position.x = x
        out.pose.position.y = y
        out.pose.position.z = z
        out.pose.orientation.w = 1.0
        self._pub.publish(out)
        if not self._have_pose:
            self._have_pose = True
            self.slog.info("First pose published", x=x, y=y, z=z)

    def destroy_node(self) -> None:
        self.slog.close()
        super().destroy_node()


def main(args: list[str] | None = None) -> None:
    rclpy.init(args=args)
    node = Px4PoseAdapter()
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
