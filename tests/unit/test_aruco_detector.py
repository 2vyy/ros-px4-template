# tests/unit/test_aruco_detector.py
"""Unit tests for ArUco detection — uses synthetic rendered markers (no camera required)."""

from __future__ import annotations

import cv2
import numpy as np
from ros_px4_template_core.lib.aruco_detector import _get_detector, detect_markers


def _render_marker(marker_id: int = 0, img_size: int = 640) -> tuple[np.ndarray, np.ndarray]:
    """Render a single ArUco marker centered in a white image. Returns (image, camera_matrix)."""
    aruco_dict = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
    marker_img = cv2.aruco.generateImageMarker(aruco_dict, marker_id, 200)
    img = np.ones((img_size, img_size, 3), dtype=np.uint8) * 255
    offset = (img_size - 200) // 2
    img[offset : offset + 200, offset : offset + 200] = cv2.cvtColor(marker_img, cv2.COLOR_GRAY2BGR)
    fx = fy = 500.0
    cx = cy = img_size / 2.0
    camera_matrix = np.array([[fx, 0, cx], [0, fy, cy], [0, 0, 1]], dtype=np.float64)
    return img, camera_matrix


def test_detects_known_marker() -> None:
    img, cam = _render_marker(marker_id=0)
    detections = detect_markers(img, cam, np.zeros((4, 1)), marker_size_m=0.2)
    assert len(detections) == 1
    assert detections[0].marker_id == 0


def test_no_detections_on_blank_image() -> None:
    img = np.ones((640, 640, 3), dtype=np.uint8) * 255
    cam = np.array([[500, 0, 320], [0, 500, 320], [0, 0, 1]], dtype=np.float64)
    detections = detect_markers(img, cam, np.zeros((4, 1)))
    assert len(detections) == 0


def test_marker_center_near_image_center() -> None:
    img, cam = _render_marker(marker_id=0, img_size=640)
    detections = detect_markers(img, cam, np.zeros((4, 1)), marker_size_m=0.2)
    assert len(detections) == 1
    d = detections[0]
    assert abs(d.center_x_px - 320) < 20
    assert abs(d.center_y_px - 320) < 20


def test_detection_has_positive_z_distance() -> None:
    img, cam = _render_marker(marker_id=0)
    detections = detect_markers(img, cam, np.zeros((4, 1)), marker_size_m=0.2)
    assert len(detections) == 1
    # Z-forward distance is the 3rd component of tvec
    assert float(detections[0].tvec_cam[2][0]) > 0


def test_returns_list_type() -> None:
    img, cam = _render_marker()
    result = detect_markers(img, cam, np.zeros((4, 1)))
    assert isinstance(result, list)


def test_uncalibrated_camera_matrix_returns_empty() -> None:
    img, _ = _render_marker(marker_id=0)
    # Passed empty/zeroed matrix
    cam = np.zeros((3, 3), dtype=np.float64)
    detections = detect_markers(img, cam, np.zeros((4, 1)), marker_size_m=0.2)
    assert len(detections) == 0


def test_detector_cached_per_dictionary() -> None:
    first = _get_detector(cv2.aruco.DICT_4X4_50)
    second = _get_detector(cv2.aruco.DICT_4X4_50)
    other = _get_detector(cv2.aruco.DICT_5X5_50)

    assert first is second
    assert first is not other


def test_detection_unchanged_after_cache() -> None:
    img, cam = _render_marker(marker_id=0)

    first = detect_markers(img, cam, np.zeros((4, 1)), marker_size_m=0.2)
    second = detect_markers(img, cam, np.zeros((4, 1)), marker_size_m=0.2)

    assert [(d.marker_id, d.center_x_px, d.center_y_px) for d in first] == [
        (d.marker_id, d.center_x_px, d.center_y_px) for d in second
    ]
