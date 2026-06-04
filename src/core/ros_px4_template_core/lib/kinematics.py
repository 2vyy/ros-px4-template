"""Rigid body kinematics for sensors.

Handles standard transformations:
Camera (Z-forward) -> Body (FLU) -> World (ENU)
"""

from __future__ import annotations

import cv2
import numpy as np
from scipy.spatial.transform import Rotation


def ensure_col_vector(v: np.ndarray | list[float]) -> np.ndarray:
    """Ensure a vector is a numpy array shaped (3, 1)."""
    return np.asarray(v, dtype=float).reshape(3, 1)


def ensure_rot_matrix(r: np.ndarray | list[float]) -> np.ndarray:
    """Ensure rotation is a 3x3 matrix (convert from Rodrigues if needed)."""
    r_arr = np.asarray(r, dtype=float)
    if r_arr.shape == (3, 3):
        return r_arr
    elif r_arr.shape == (3, 1) or r_arr.shape == (3,):
        mat, _ = cv2.Rodrigues(r_arr.reshape(3, 1))
        return mat
    raise ValueError(f"Invalid rotation shape: {r_arr.shape}")


def camera_to_body(
    tvec_c: np.ndarray,
    rvec_c: np.ndarray,
    cam_ext_t: np.ndarray,
    cam_ext_r: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Transform a pose from camera frame to drone body frame (FLU).

    Args:
        tvec_c: Translation vector of marker in camera frame (3x1).
        rvec_c: Rotation vector of marker in camera frame (3x1 Rodrigues).
        cam_ext_t: Camera translation relative to body CG (3x1).
        cam_ext_r: Camera rotation relative to body (3x3).

    Returns:
        body_pos (3x1), body_quat (x, y, z, w)
    """
    t_c = ensure_col_vector(tvec_c)
    r_c = ensure_rot_matrix(rvec_c)

    body_pos = (cam_ext_r @ t_c) + ensure_col_vector(cam_ext_t)
    body_r = cam_ext_r @ r_c
    body_quat = Rotation.from_matrix(body_r).as_quat()

    return body_pos, body_quat


def camera_to_world(
    tvec_c: np.ndarray,
    rvec_c: np.ndarray,
    cam_ext_t: np.ndarray,
    cam_ext_r: np.ndarray,
    drone_w_pos: np.ndarray,
    drone_w_quat: np.ndarray | list[float],
) -> tuple[np.ndarray, np.ndarray]:
    """Transform a pose from camera frame directly to World ENU frame.

    Args:
        drone_w_pos: Drone position in world ENU (3x1).
        drone_w_quat: Drone orientation in world ENU [x,y,z,w].

    Returns:
        world_pos (3x1), world_quat (x, y, z, w)
    """
    body_pos, body_quat = camera_to_body(tvec_c, rvec_c, cam_ext_t, cam_ext_r)

    drone_r = Rotation.from_quat(drone_w_quat).as_matrix()

    world_pos = (drone_r @ body_pos) + ensure_col_vector(drone_w_pos)
    world_r = drone_r @ Rotation.from_quat(body_quat).as_matrix()
    world_quat = Rotation.from_matrix(world_r).as_quat()

    return world_pos, world_quat


def world_to_body(
    marker_w_pos: np.ndarray,
    marker_w_quat: np.ndarray | list[float],
    tvec_c: np.ndarray,
    rvec_c: np.ndarray,
    cam_ext_t: np.ndarray,
    cam_ext_r: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Infer the drone body pose based on a known marker world pose.

    Calculates where the drone MUST be to see the marker at (tvec_c, rvec_c).

    Returns:
        drone_w_pos (3x1), drone_w_quat (x, y, z, w)
    """
    t_c = ensure_col_vector(tvec_c)
    r_c = ensure_rot_matrix(rvec_c)

    # r_world = r_drone @ r_cam_ext @ r_marker_in_cam
    # So r_drone = r_world @ (r_cam_ext @ r_marker_in_cam)^-1
    r_world = Rotation.from_quat(marker_w_quat).as_matrix()
    r_marker_body = cam_ext_r @ r_c

    # Transpose is the inverse for rotation matrices and numerically safer
    r_drone = r_world @ r_marker_body.T
    drone_w_quat = Rotation.from_matrix(r_drone).as_quat()

    # pos_world_marker = pos_world_drone + r_drone @ pos_body_marker
    # So pos_world_drone = pos_world_marker - r_drone @ pos_body_marker
    body_pos = (cam_ext_r @ t_c) + ensure_col_vector(cam_ext_t)
    drone_w_pos = ensure_col_vector(marker_w_pos) - (r_drone @ body_pos)

    return drone_w_pos, drone_w_quat
