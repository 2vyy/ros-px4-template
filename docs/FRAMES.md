# Frames

All application code runs in **ENU** (East-North-Up, [REP-103](https://www.ros.org/reps/rep-0103.html)). PX4 uXRCE topics are **NED**. Conversion happens only at the PX4 boundary.

## World frames

| Frame | X | Y | Z | Used by |
|-------|---|---|---|---------|
| ENU | East | North | Up | `/drone/*`, missions, scenarios, `lib/` |
| NED | North | East | Down | `/fmu/in/*`, `/fmu/out/*` from PX4 |

Position swap (no rotation matrix in v1):

```text
x_enu = y_ned    y_enu = x_ned    z_enu = -z_ned
```

Implementation: `ned_to_enu` and `enu_to_ned` in `src/core/ros_px4_template_core/lib/frames.py`.

| Call site | Direction |
|-----------|-----------|
| `offboard_controller` | ENU setpoints become NED `TrajectorySetpoint` on publish |
| `mission_manager` | NED `VehicleLocalPosition` becomes ENU for mission logic |
| Scenarios (`tests/scenarios/`) | NED telemetry becomes ENU for assertions |

Do not mix NED coordinates into mission YAML or `/drone/*` topics.

## Body frames

| Convention | X | Y | Z | Typical use |
|------------|---|---|---|-------------|
| FLU (ROS REP-103 body) | Forward | Left | Up | `geometry_msgs` poses, future attitude commands |
| FRD (PX4 body) | Forward | Right | Down | PX4 setpoints when roll/pitch/yaw are populated |

This template streams position-only offboard setpoints. `offboard_controller` sets `yaw = NaN` so PX4 holds current heading. There is no FLU/FRD attitude conversion in the tree yet.

When you add body-frame velocity or attitude:

- Map FLU linear and angular rates to FRD before publishing to `/fmu/in/trajectory_setpoint`.
- Yaw sign: REP-103 ENU uses yaw positive counter-clockwise about +Z; PX4 NED yaw is positive clockwise about +Z (down). Negate yaw (and verify roll/pitch sign) at the same boundary as position.

## Z axis

ENU altitude grows with +Z. NED altitude grows as `z_ned` becomes more negative. A hover at 3 m AGL is roughly `z_enu = 3`, `z_ned = -3`.

## Mission pose

`mission_manager` consumes `/drone/odom` (`nav_msgs/Odometry`, frame `map`, `RELIABLE` QoS), published by `position_node` from PX4's `/fmu/out/vehicle_local_position_v1` in the anchored ENU frame (see [TOPICS.md](TOPICS.md)). Mission logic blends odom z with `controller_status.altitude_enu_m` (`z_eff = max(pose_z, controller_alt)`) so the takeoff gate works before the first odom fix. Do not feed mission logic raw `/fmu/out/vehicle_local_position` - it is NED and unanchored.

## Quick checks

- Path files under `config/paths/` use ENU meters.
- Comparing to `/fmu/out/vehicle_local_position` without `ned_to_enu` looks mirrored or swapped.
- Body-frame bugs show up as wrong lateral direction or inverted climb once yaw or velocity setpoints are non-NaN.

## Camera frame

When doing computer vision (e.g. ArUco detection), the camera frame uses the OpenCV optical convention:

| Axis | Direction |
|------|-----------|
| X | Right |
| Y | Down |
| Z | Forward (into the scene) |

`camera_to_body(tvec_cam, cam_ext_r, cam_ext_t)` maps a camera-optical point to body FLU (`R_ext @ t + t_ext`). It is position-only; marker orientation is not recovered (no 6-DOF pose chain in the tree). Localization to the world is then `marker_world_from_drone` (forward) or `drone_pose_from_marker` (inverse), using the drone yaw.

Represent static camera extrinsics (`cam_ext_r`, `cam_ext_t`) as the transform from the Camera to the Body (FLU) frame. A downward-facing (nadir) camera aligned with the drone has:

```text
Body X (Forward) = -Cam Y
Body Y (Left)    = -Cam X
Body Z (Up)      = -Cam Z
```

## Pure frame core

`lib/frames.py` is the single authoritative home for the pure, stateless transforms (`math`/`numpy` only, no `rclpy`/`cv2`/`scipy`). The module docstring is the source of truth for the formulas; the public functions are:

| Function | Purpose |
|----------|---------|
| `ned_to_enu` / `enu_to_ned` | World position swap across the PX4 boundary |
| `enu_yaw_from_heading` | PX4 NED heading (0=North, CW+) becomes ENU yaw (0=East, CCW+), wrapped to [-pi, pi] |
| `px4_local_z_ned` | Normalize `VehicleLocalPosition.z` to local NED (zero at boot) |
| `enu_setpoint_to_px4_ned` | Anchored-ENU setpoint becomes PX4 local NED (origin + EKF-reset adjust) |
| `body_flu_to_enu_offset` | Rotate a body-FLU horizontal offset into ENU by drone yaw |
| `marker_world_from_drone` | Forward localization: drone world pose + body offset becomes marker world pose |
| `drone_pose_from_marker` | Inverse (relocalization): marker world pose + body offset becomes drone world pose |
| `camera_to_body` | Camera-optical point becomes body FLU (position-only) |

The stateful takeoff-origin / EKF-reset tracker `Px4LocalFrame` lives in `lib/px4_local_frame.py` and imports the core.

### Assumption: yaw-only / level flight

The body-to-world offset helpers use the drone yaw only; roll and pitch are neglected (vehicle treated as level, camera as nadir). This is valid because the vehicle never tilts fast or far enough for the residual offset error to matter for these tasks. A fork needing tilt-accurate localization must extend the offset rotation to full attitude.
