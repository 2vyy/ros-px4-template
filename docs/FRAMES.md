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

Implementation: `ned_to_enu` and `enu_to_ned` in `src/core/ros_px4_template_core/lib/frame_transforms.py`.

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

`mission_manager` uses `/drone/pose_enu` (`geometry_msgs/PoseStamped`, frame `map`). Sim: `sim_pose_adapter` (Gazebo model pose via `ros_gz_bridge`, started after the model topic is live). Hardware: `px4_pose_adapter` (PX4 NED converted to ENU). Do not feed mission logic raw `/fmu/out/vehicle_local_position`.

## Quick checks

- Path files under `config/paths/` use ENU meters.
- Comparing to `/fmu/out/vehicle_local_position` without `ned_to_enu` looks mirrored or swapped.
- Body-frame bugs show up as wrong lateral direction or inverted climb once yaw or velocity setpoints are non-NaN.
