# src/core/ros_px4_template_core/lib/aruco_detector.py
"""ArUco marker detection — pure OpenCV, no ROS.

Requires opencv-python >= 4.7.0 (aruco is in the main package since 4.7).

Camera frame convention: X right, Y down, Z forward (into scene).
For a nadir (downward-facing) camera:
    body_forward_m  ≈ -tvec.y   (image down  → body forward)
    body_left_m     ≈ -tvec.x   (image right → body left inverted)
    altitude_to_marker_m ≈ tvec.z
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


@dataclass(frozen=True)
class MarkerDetection:
    marker_id: int
    center_x_px: float
    center_y_px: float
    rvec: np.ndarray
    tvec: np.ndarray

    @property
    def z_camera_m(self) -> float:
        """Distance from camera to marker along camera Z axis (forward).

        cv2.solvePnP returns tvec of shape (3, 1), so tvec[2][0] is the Z component.
        """
        return float(self.tvec[2][0])

    @property
    def x_camera_m(self) -> float:
        return float(self.tvec[0][0])

    @property
    def y_camera_m(self) -> float:
        return float(self.tvec[1][0])

    @property
    def distance_m(self) -> float:
        return float(np.linalg.norm(self.tvec))

    @property
    def enu_east_m(self) -> float:
        """ENU east offset (nadir camera, drone heading ≈ north): -tvec.y."""
        return float(-self.tvec[1][0])

    @property
    def enu_north_m(self) -> float:
        """ENU north offset (nadir camera, drone heading ≈ north): -tvec.x."""
        return float(-self.tvec[0][0])


def detect_markers(
    image: np.ndarray,
    camera_matrix: np.ndarray,
    dist_coeffs: np.ndarray,
    marker_size_m: float = 0.2,
    dictionary_id: int = cv2.aruco.DICT_4X4_50,
) -> list[MarkerDetection]:
    """Detect ArUco markers in an image and estimate 3D pose."""
    aruco_dict = cv2.aruco.getPredefinedDictionary(dictionary_id)
    params = cv2.aruco.DetectorParameters()
    detector = cv2.aruco.ArucoDetector(aruco_dict, params)
    corners, ids, _ = detector.detectMarkers(image)

    if ids is None or len(ids) == 0:
        return []

    half = marker_size_m / 2.0
    obj_pts = np.array(
        [[-half, half, 0], [half, half, 0], [half, -half, 0], [-half, -half, 0]],
        dtype=np.float32,
    )

    results: list[MarkerDetection] = []
    for corner, marker_id in zip(corners, ids, strict=True):
        ok, rvec, tvec = cv2.solvePnP(obj_pts, corner[0], camera_matrix, dist_coeffs)
        if not ok:
            continue
        cx = float(np.mean(corner[0, :, 0]))
        cy = float(np.mean(corner[0, :, 1]))
        results.append(
            MarkerDetection(
                marker_id=int(marker_id[0]),
                center_x_px=cx,
                center_y_px=cy,
                rvec=rvec,
                tvec=tvec,
            )
        )
    return results
