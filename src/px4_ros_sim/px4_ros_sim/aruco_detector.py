"""Sim-only ArUco detector — publishes /vision/marker_pose in map frame."""

from __future__ import annotations

import cv2
import numpy as np
import rclpy
from geometry_msgs.msg import PoseStamped
from rclpy.node import Node
from rclpy.qos import HistoryPolicy, QoSProfile, ReliabilityPolicy
from sensor_msgs.msg import Image

try:
    aruco = cv2.aruco
except AttributeError:
    from cv2 import aruco  # type: ignore[attr-defined]

_RELIABLE_QOS = QoSProfile(
    reliability=ReliabilityPolicy.RELIABLE,
    history=HistoryPolicy.KEEP_LAST,
    depth=5,
)


class ArucoDetector(Node):
    """Detect DICT_4X4_50 markers; publish known map pose when seen.

    SIM SHORTCUT: publishes the world-frame pose from ``marker_world_*`` params,
    NOT the pose estimated from the detected marker corners. Real detection
    requires camera intrinsics, solvePnP, and a proper TF chain.
    """

    def __init__(self) -> None:
        super().__init__("aruco_detector")
        self.declare_parameter("camera_topic", "/camera/image_raw")
        self.declare_parameter("marker_id", 0)
        self.declare_parameter("marker_size_m", 0.5)
        self.declare_parameter("marker_world_x", 8.0)
        self.declare_parameter("marker_world_y", 0.0)
        self.declare_parameter("marker_world_z", 0.0)
        self.declare_parameter("frame_id", "map")

        topic = str(self.get_parameter("camera_topic").value)
        self._marker_id = int(self.get_parameter("marker_id").value)
        self._dict = aruco.getPredefinedDictionary(aruco.DICT_4X4_50)
        self._params = aruco.DetectorParameters()
        self._detector = aruco.ArucoDetector(self._dict, self._params)
        self._world = (
            float(self.get_parameter("marker_world_x").value),
            float(self.get_parameter("marker_world_y").value),
            float(self.get_parameter("marker_world_z").value),
        )
        self._frame_id = str(self.get_parameter("frame_id").value)

        self._pub = self.create_publisher(PoseStamped, "/vision/marker_pose", _RELIABLE_QOS)
        self.create_subscription(Image, topic, self._image_cb, _RELIABLE_QOS)
        self.get_logger().info(f"ArucoDetector listening on {topic}")

    def _image_cb(self, msg: Image) -> None:
        if msg.encoding not in ("rgb8", "bgr8", "mono8"):
            return
        h, w = msg.height, msg.width
        if msg.encoding == "mono8":
            gray = np.frombuffer(msg.data, dtype=np.uint8).reshape((h, w))
        elif msg.encoding == "rgb8":
            rgb = np.frombuffer(msg.data, dtype=np.uint8).reshape((h, w, 3))
            gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
        else:
            bgr = np.frombuffer(msg.data, dtype=np.uint8).reshape((h, w, 3))
            gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)

        _corners, ids, _ = self._detector.detectMarkers(gray)
        if ids is None:
            return
        for mid in ids.flatten():
            if int(mid) != self._marker_id:
                continue
            pose = PoseStamped()
            pose.header.stamp = self.get_clock().now().to_msg()
            pose.header.frame_id = self._frame_id
            pose.pose.position.x = self._world[0]
            pose.pose.position.y = self._world[1]
            pose.pose.position.z = self._world[2]
            pose.pose.orientation.w = 1.0
            self._pub.publish(pose)
            return


def main(args: list[str] | None = None) -> None:
    rclpy.init(args=args)
    node = ArucoDetector()
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
