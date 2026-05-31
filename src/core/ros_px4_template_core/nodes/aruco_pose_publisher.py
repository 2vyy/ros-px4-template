"""ArUco marker pose publisher.

=============================================================================
ROS 2 Interface
=============================================================================
Subscriptions:
    /camera/image_raw      [sensor_msgs/Image]       — camera feed
    /camera/camera_info    [sensor_msgs/CameraInfo]  — intrinsics

Publishers:
    /drone/marker_detected   [std_msgs/Bool]                      — true when marker visible
    /drone/marker_offset_enu [geometry_msgs/Vector3Stamped]       — ENU offset drone→marker (m)
=============================================================================

Camera mounting assumption: nadir (straight down), camera X right = body right.
ENU offset derivation:
    body_forward_m = -tvec.y  (image Y down → body forward)
    body_left_m    = -tvec.x  (image X right → body left, inverted)
Yaw correction is NOT applied — offset is body-frame approximated as ENU
when drone heading ≈ 0 (north-facing). Add heading correction when yaw source is wired.
"""

from __future__ import annotations

import numpy as np
import rclpy
from cv_bridge import CvBridge
from geometry_msgs.msg import Vector3Stamped
from rclpy.node import Node
from rclpy.qos import HistoryPolicy, QoSProfile, ReliabilityPolicy
from sensor_msgs.msg import CameraInfo, Image
from std_msgs.msg import Bool

from ros_px4_template_core.lib.aruco_detector import detect_markers

_RELIABLE_QOS = QoSProfile(
    reliability=ReliabilityPolicy.RELIABLE,
    history=HistoryPolicy.KEEP_LAST,
    depth=10,
)


class ArucoPosePublisher(Node):
    """Detects ArUco markers and publishes drone-relative ENU offset."""

    def __init__(self) -> None:
        super().__init__("aruco_pose_publisher")
        self.declare_parameter("target_marker_id", 0)
        self.declare_parameter("marker_length_m", 0.2)

        self._target_id = int(self.get_parameter("target_marker_id").value)
        self._marker_length = float(self.get_parameter("marker_length_m").value)
        self._bridge = CvBridge()
        self._camera_matrix: np.ndarray | None = None
        self._dist_coeffs: np.ndarray | None = None

        self.create_subscription(Image, "/camera/image_raw", self._image_cb, _RELIABLE_QOS)
        self.create_subscription(CameraInfo, "/camera/camera_info", self._info_cb, _RELIABLE_QOS)

        self._pub_detected = self.create_publisher(Bool, "/drone/marker_detected", _RELIABLE_QOS)
        self._pub_offset = self.create_publisher(
            Vector3Stamped, "/drone/marker_offset_enu", _RELIABLE_QOS
        )

    def _info_cb(self, msg: CameraInfo) -> None:
        if self._camera_matrix is None:
            self._camera_matrix = np.array(msg.k).reshape(3, 3)
            self._dist_coeffs = np.array(msg.d).reshape(-1, 1)
            self.get_logger().info("Camera intrinsics received.")

    def _image_cb(self, msg: Image) -> None:
        if self._camera_matrix is None:
            return

        try:
            cv_img = self._bridge.imgmsg_to_cv2(msg, desired_encoding="bgr8")
        except Exception as exc:
            self.get_logger().warn(f"Image conversion failed: {exc}")
            return

        detections = detect_markers(
            cv_img, self._camera_matrix, self._dist_coeffs, self._marker_length
        )
        target = next((d for d in detections if d.marker_id == self._target_id), None)

        detected_msg = Bool()
        detected_msg.data = target is not None
        self._pub_detected.publish(detected_msg)

        if target is None:
            return

        offset = Vector3Stamped()
        offset.header.stamp = msg.header.stamp
        offset.header.frame_id = "base_link"
        offset.vector.x = float(-target.y_camera_m)
        offset.vector.y = float(-target.x_camera_m)
        offset.vector.z = 0.0
        self._pub_offset.publish(offset)

    def destroy_node(self) -> None:
        super().destroy_node()


def main(args: list[str] | None = None) -> None:
    rclpy.init(args=args)
    node = ArucoPosePublisher()
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
