"""ArUco marker detection — pure OpenCV, no ROS.

Camera frame convention: X right, Y down, Z forward (into scene).
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


@dataclass
class MarkerDetection:
    marker_id: int
    center_x_px: float
    center_y_px: float
    rvec_cam: np.ndarray
    tvec_cam: np.ndarray


def detect_markers(
    image: np.ndarray,
    camera_matrix: np.ndarray,
    dist_coeffs: np.ndarray,
    marker_size_m: float = 0.2,
    dictionary_id: int = cv2.aruco.DICT_4X4_50,
) -> list[MarkerDetection]:
    """Detect ArUco markers in an image and estimate 3D pose in camera frame.

    Args:
        dist_coeffs: Distortion coefficients of shape ``(N,)`` or ``(N, 1)``
            as returned by ``cv2.calibrateCamera``.
    """
    # Guard clause against uncalibrated cameras starting up with empty matrices
    if camera_matrix is None or not np.any(camera_matrix):
        return []

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
        # cv2.SOLVEPNP_IPPE_SQUARE is mathematically optimized for flat squares
        # and drastically reduces pose flip ambiguity/rotational jitter over ITERATIVE.
        ok, rvec, tvec = cv2.solvePnP(
            obj_pts, corner[0], camera_matrix, dist_coeffs, flags=cv2.SOLVEPNP_IPPE_SQUARE
        )
        if not ok:
            continue

        cx = float(np.mean(corner[0, :, 0]))
        cy = float(np.mean(corner[0, :, 1]))
        results.append(
            MarkerDetection(
                marker_id=int(marker_id[0]),
                center_x_px=cx,
                center_y_px=cy,
                rvec_cam=rvec,
                tvec_cam=tvec,
            )
        )
    return results
