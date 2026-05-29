"""Publish /drone/pose_enu from Gazebo model pose (sim ground-truth backend).

Subscribes to a ros_gz_bridge PoseStamped topic (Gazebo world/model pose).
Republishes with frame_id map for mission_manager.

=============================================================================
ROS 2 Interface
=============================================================================

Subscriptions:
    gz_model_pose  [geometry_msgs/PoseStamped]  (remapped from launch)

Publishers:
    /drone/pose_enu  [geometry_msgs/PoseStamped]
=============================================================================
"""

from __future__ import annotations

import rclpy
from geometry_msgs.msg import PoseStamped
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy

POSE_ENU_TOPIC = "/drone/pose_enu"

_POSE_QOS = QoSProfile(
    reliability=ReliabilityPolicy.BEST_EFFORT,
    durability=DurabilityPolicy.VOLATILE,
    history=HistoryPolicy.KEEP_LAST,
    depth=10,
)


class SimPoseAdapter(Node):
    """Gazebo ground-truth pose to canonical /drone/pose_enu."""

    def __init__(self) -> None:
        super().__init__("sim_pose_adapter")
        self.declare_parameter("frame_id", "map")
        self.declare_parameter("input_topic", "/gz/model/pose")
        self._frame_id = str(self.get_parameter("frame_id").value)
        input_topic = str(self.get_parameter("input_topic").value)
        self._pub = self.create_publisher(PoseStamped, POSE_ENU_TOPIC, _POSE_QOS)
        self.create_subscription(PoseStamped, input_topic, self._pose_cb, _POSE_QOS)
        self.get_logger().info(f"SimPoseAdapter: {input_topic} -> {POSE_ENU_TOPIC}")

    def _pose_cb(self, msg: PoseStamped) -> None:
        out = PoseStamped()
        out.header.stamp = self.get_clock().now().to_msg()
        out.header.frame_id = self._frame_id
        out.pose = msg.pose
        self._pub.publish(out)


def main(args: list[str] | None = None) -> None:
    rclpy.init(args=args)
    node = SimPoseAdapter()
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
