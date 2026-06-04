"""Publish /drone/pose_enu from Gazebo pose/info (sim ground-truth backend).

Subscribes to /world/{world}/pose/info via gz.transport (Pose_V) and extracts
the configured model pose by name. Harmonic/PX4 SITL does not publish
/world/.../model/{name}/pose; pose/info is the stable source.

=============================================================================
ROS 2 Interface
=============================================================================

Subscriptions:
    (none — Gazebo Transport /world/{world}/pose/info)

Publishers:
    /drone/pose_enu  [geometry_msgs/PoseStamped]
=============================================================================
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

import gz.transport13 as gz_transport
import rclpy
from geometry_msgs.msg import PoseStamped
from gz.msgs10.pose_v_pb2 import Pose_V
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
from ros_px4_template_core.lib.structured_logger import StructuredLogger

from px4_ros_sim.sim_pose_lookup import find_named_pose_in_list

if TYPE_CHECKING:
    from gz.msgs10.pose_pb2 import Pose

POSE_ENU_TOPIC = "/drone/pose_enu"

_POSE_QOS = QoSProfile(
    reliability=ReliabilityPolicy.RELIABLE,
    durability=DurabilityPolicy.VOLATILE,
    history=HistoryPolicy.KEEP_LAST,
    depth=10,
)


def find_named_pose(msg: Pose_V, model_name: str) -> Pose | None:
    """Return the Gazebo pose entry matching model_name, or None."""
    found = find_named_pose_in_list(list(msg.pose), model_name)
    return found  # type: ignore[return-value]


class SimPoseAdapter(Node):
    """Gazebo ground-truth pose to canonical /drone/pose_enu."""

    def __init__(self) -> None:
        super().__init__("sim_pose_adapter")
        self.declare_parameter("world", "default")
        self.declare_parameter("model_name", "x500_0")
        self.declare_parameter("frame_id", "map")
        self.declare_parameter("log_dir", "./logs")
        world = str(self.get_parameter("world").value)
        self._model_name = str(self.get_parameter("model_name").value)
        self._frame_id = str(self.get_parameter("frame_id").value)
        log_dir = str(self.get_parameter("log_dir").value)
        self.slog = StructuredLogger(self, log_dir=log_dir)
        self._have_pose = False
        self._lock = threading.Lock()
        self._latest: Pose | None = None
        self._pub = self.create_publisher(PoseStamped, POSE_ENU_TOPIC, _POSE_QOS)
        self.create_timer(0.05, self._publish_latest)
        gz_topic = f"/world/{world}/pose/info"
        self._gz_node = gz_transport.Node()
        ok = self._gz_node.subscribe(Pose_V, gz_topic, self._gz_pose_cb)
        if not ok:
            raise RuntimeError(f"SimPoseAdapter: failed to subscribe to {gz_topic}")
        self.slog.info(
            "SimPoseAdapter ready",
            gz_topic=gz_topic,
            model_name=self._model_name,
            frame_id=self._frame_id,
        )

    def _gz_pose_cb(self, msg: Pose_V) -> None:
        entry = find_named_pose(msg, self._model_name)
        if entry is None:
            return
        with self._lock:
            self._latest = entry

    def _publish_latest(self) -> None:
        with self._lock:
            entry = self._latest
        if entry is None:
            return
        out = PoseStamped()
        out.header.stamp = self.get_clock().now().to_msg()
        out.header.frame_id = self._frame_id
        out.pose.position.x = entry.position.x
        out.pose.position.y = entry.position.y
        out.pose.position.z = entry.position.z
        out.pose.orientation.x = entry.orientation.x
        out.pose.orientation.y = entry.orientation.y
        out.pose.orientation.z = entry.orientation.z
        out.pose.orientation.w = entry.orientation.w
        self._pub.publish(out)
        if not self._have_pose:
            self._have_pose = True
            self.slog.info(
                "First pose published",
                x=entry.position.x,
                y=entry.position.y,
                z=entry.position.z,
            )

    def destroy_node(self) -> None:
        self.slog.close()
        super().destroy_node()


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
