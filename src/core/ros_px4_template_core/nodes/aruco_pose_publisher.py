"""ArUco marker pose publisher.

=============================================================================
ROS 2 Interface
Subscriptions:
    /camera/image_raw      [sensor_msgs/Image]       — camera feed
    /camera/camera_info    [sensor_msgs/CameraInfo]  — intrinsics
Publishers:
    /drone/marker_detection  [px4_ros_msgs/MarkerDetection]  — id + FLU offset drone→marker (m)
=============================================================================

Camera mounting assumption: nadir (straight down), camera X right = body right.
Publishes offset in base_link (Forward-Left-Up).
"""

from __future__ import annotations

import numpy as np
import rclpy
from cv_bridge import CvBridge
from px4_ros_msgs.msg import MarkerDetection
from rclpy.node import Node
from rclpy.qos import HistoryPolicy, QoSProfile, ReliabilityPolicy
from sensor_msgs.msg import CameraInfo, Image

from ros_px4_template_core.lib.aruco_detector import detect_markers
from ros_px4_template_core.lib.frames import camera_to_body

_RELIABLE_QOS = QoSProfile(
    reliability=ReliabilityPolicy.RELIABLE,
    history=HistoryPolicy.KEEP_LAST,
    depth=10,
)


class ArucoPosePublisher(Node):
    """Detects ArUco markers and publishes a MarkerDetection (body-FLU offset)."""

    def __init__(self) -> None:
        super().__init__("aruco_pose_publisher")
        self.declare_parameter("target_marker_id", 0)
        self.declare_parameter("marker_size_m", 0.2)

        self._target_id = int(self.get_parameter("target_marker_id").value)
        self._marker_size = float(self.get_parameter("marker_size_m").value)
        self._bridge = CvBridge()
        self._camera_matrix: np.ndarray | None = None
        self._dist_coeffs: np.ndarray | None = None

        self.create_subscription(Image, "/camera/image_raw", self._image_cb, _RELIABLE_QOS)
        self.create_subscription(CameraInfo, "/camera/camera_info", self._info_cb, _RELIABLE_QOS)
        self._pub = self.create_publisher(MarkerDetection, "/drone/marker_detection", _RELIABLE_QOS)

    def _info_cb(self, msg: CameraInfo) -> None:
        if self._camera_matrix is None:
            self._camera_matrix = np.array(msg.k).reshape(3, 3)
            self._dist_coeffs = np.array(msg.d).reshape(-1, 1)  # (N,1) for solvePnP
            self.get_logger().info("Camera intrinsics received.")

    def _publish(
        self,
        stamp,
        *,
        valid: bool,
        marker_id: int = 0,
        offset: tuple[float, float, float] = (0.0, 0.0, 0.0),
    ) -> None:
        det = MarkerDetection()
        det.header.stamp = stamp
        det.header.frame_id = "base_link"
        det.id = int(marker_id)
        det.offset_body_flu.x = float(offset[0])
        det.offset_body_flu.y = float(offset[1])
        det.offset_body_flu.z = float(offset[2])
        det.has_world_pose = False
        det.valid = valid
        self._pub.publish(det)

    def _image_cb(self, msg: Image) -> None:
        if self._camera_matrix is None:
            return
        try:
            cv_img = self._bridge.imgmsg_to_cv2(msg, desired_encoding="bgr8")
        except Exception as exc:
            self.get_logger().warn(f"Image conversion failed: {exc}")
            return

        detections = detect_markers(
            cv_img, self._camera_matrix, self._dist_coeffs, self._marker_size
        )
        target = next((d for d in detections if d.marker_id == self._target_id), None)
        if target is None:
            self._publish(msg.header.stamp, valid=False, marker_id=self._target_id)
            return

        # Map camera to base_link (assume nadir perfectly aligned)
        cam_ext_t = np.zeros((3, 1))
        cam_ext_r = np.array([[0, -1, 0], [-1, 0, 0], [0, 0, -1]])
        offset = camera_to_body(target.tvec_cam, cam_ext_r, cam_ext_t)
        self._publish(
            msg.header.stamp,
            valid=True,
            marker_id=target.marker_id,
            offset=offset,
        )


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
