import numpy as np
from ros_px4_template_core.lib.kinematics import (
    camera_to_body,
    camera_to_world,
    world_to_body,
)
from scipy.spatial.transform import Rotation


def test_camera_to_body_nadir():
    """Test camera to body transformation for a nadir (downward-facing) camera."""
    # A standard nadir camera looking straight down relative to the drone
    # Drone (FLU): X=Forward, Y=Left, Z=Up
    # Camera: Z=Forward(into scene), X=Right, Y=Down
    # For Nadir: Camera Z = Body -Z, Camera X = Body -Y, Camera Y = Body -X

    # Marker detected in center of image, 5 meters away (along camera Z)
    tvec_c = np.array([[0.0], [0.0], [5.0]])
    # Marker is flat facing the camera (no rotation relative to camera)
    rvec_c = np.array([[0.0], [0.0], [0.0]])

    # Camera mounted exactly at CG
    cam_ext_t = np.zeros((3, 1))

    # Rotation from Camera to Body
    cam_ext_r = np.array([[0, -1, 0], [-1, 0, 0], [0, 0, -1]])

    body_pos, _body_quat = camera_to_body(tvec_c, rvec_c, cam_ext_t, cam_ext_r)

    # The marker should be 5 meters exactly DOWN (-Z in body frame)
    assert np.allclose(body_pos, np.array([[0.0], [0.0], [-5.0]]))


def test_camera_to_world_drone_rotated():
    """Test full chain: Camera -> Body -> World with drone yawed 90 degrees."""
    # Marker is 2 meters right of center in camera frame (Cam X = 2.0)
    tvec_c = np.array([[2.0], [0.0], [5.0]])
    rvec_c = np.zeros((3, 1))

    cam_ext_t = np.zeros((3, 1))
    cam_ext_r = np.array([[0, -1, 0], [-1, 0, 0], [0, 0, -1]])

    # Drone is at World ENU (10, 10, 10)
    drone_w_pos = np.array([[10.0], [10.0], [10.0]])
    # Drone is yawed 90 degrees CCW (facing North/Y-axis)
    drone_w_quat = Rotation.from_euler("z", 90, degrees=True).as_quat()

    world_pos, _world_quat = camera_to_world(
        tvec_c, rvec_c, cam_ext_t, cam_ext_r, drone_w_pos, drone_w_quat
    )

    expected_world_pos = np.array([[12.0], [10.0], [5.0]])
    assert np.allclose(world_pos, expected_world_pos, atol=1e-5)


def test_world_to_body_localization():
    """Test inferring drone body pose from a known marker world pose."""
    # Marker is at World (0, 0, 0)
    marker_w_pos = np.array([[0.0], [0.0], [0.0]])
    # Marker has identity rotation (aligned with ENU)
    marker_w_quat = np.array([0.0, 0.0, 0.0, 1.0])

    # Drone camera sees the marker exactly 3 meters below it (Camera Z = 3.0)
    # and 1 meter in front of drone (Camera Y = -1.0)
    tvec_c = np.array([[0.0], [-1.0], [3.0]])

    # World R Body for Yaw 90:
    r_w_b = Rotation.from_euler("z", 90, degrees=True).as_matrix()
    cam_ext_r = np.array([[0, -1, 0], [-1, 0, 0], [0, 0, -1]])
    r_w_c = r_w_b @ cam_ext_r
    rvec_c = Rotation.from_matrix(r_w_c.T).as_rotvec().reshape(3, 1)

    cam_ext_t = np.zeros((3, 1))

    drone_w_pos, drone_w_quat = world_to_body(
        marker_w_pos, marker_w_quat, tvec_c, rvec_c, cam_ext_t, cam_ext_r
    )

    expected_pos = np.array([[0.0], [-1.0], [3.0]])
    assert np.allclose(drone_w_pos, expected_pos, atol=1e-5)

    # Check if yaw is roughly 90 degrees
    drone_yaw = Rotation.from_quat(drone_w_quat).as_euler("xyz", degrees=True)[2]
    assert np.isclose(drone_yaw, 90.0)
