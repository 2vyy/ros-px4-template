# Topic manifest

Validated against a running stack with `just check-topics`. The checker greps backtick-quoted topic names (e.g. the rows below) out of this file and confirms each one appears in `ros2 topic list`, so keep topic names backticked.

## PX4 v1 relay

PX4 1.17 with uXRCE publishes `*_v1` topics. Node `px4_topic_relay` (`src/core/ros_px4_template_core/nodes/px4_topic_relay.py`) subscribes to those and republishes them under the legacy names that core nodes expect.

| Source (PX4) | Republished as |
|--------------|----------------|
| `/fmu/out/vehicle_local_position_v1` | `/fmu/out/vehicle_local_position` |
| `/fmu/out/vehicle_status_v1` | `/fmu/out/vehicle_status` |

## Topics

| Topic | Type | Dir | Owner |
|-------|------|-----|-------|
| `/clock` | `rosgraph_msgs/msg/Clock` | pub | clock_bridge in `sim/launch/sim_full.launch.py` |
| `/fmu/out/vehicle_local_position` | `px4_msgs/msg/VehicleLocalPosition` | pub | `px4_topic_relay` (from `_v1`) |
| `/fmu/out/vehicle_status` | `px4_msgs/msg/VehicleStatus` | pub | `px4_topic_relay` (from `_v1`) |
| `/fmu/in/trajectory_setpoint` | `px4_msgs/msg/TrajectorySetpoint` | pub | `offboard_controller` |
| `/fmu/in/offboard_control_mode` | `px4_msgs/msg/OffboardControlMode` | pub | `offboard_controller` |
| `/fmu/in/vehicle_command` | `px4_msgs/msg/VehicleCommand` | pub | `offboard_controller` |
| `/drone/target_pose` | `geometry_msgs/msg/PoseStamped` | pub | `mission_manager` |
| `/drone/controller_status` | `px4_ros_msgs/msg/ControllerStatus` | pub | `offboard_controller` |
| `/drone/mission_status` | `px4_ros_msgs/msg/MissionStatus` | pub | `mission_manager` |
| `/drone/mission_markers` | `visualization_msgs/msg/MarkerArray` | pub | `mission_manager` |
| `/vision/marker_pose` | `geometry_msgs/msg/PoseStamped` | pub | `aruco_detector` (sim only, started when `enable_vision:=true`) |

### Subscriptions

| Topic | Subscribers |
|-------|-------------|
| `/fmu/out/vehicle_local_position` | `offboard_controller`, `mission_manager`, `state_estimator` (subscriber; no publish) |
| `/fmu/out/vehicle_status` | `offboard_controller` |
| `/drone/target_pose` | `offboard_controller` |
| `/drone/controller_status` | `mission_manager` |
| `/vision/marker_pose` | `mission_manager` |

## QoS

- PX4 topics (`/fmu/*`): `BEST_EFFORT` reliability, `TRANSIENT_LOCAL` durability, `KEEP_LAST` depth 10. Defined in each node and as `PX4_QOS` in `tests/scenarios/_common.py`.
- Drone status and target topics (`/drone/*`): `RELIABLE`, `KEEP_LAST` depth 10.

## Adding a topic

1. Publish or subscribe in a node under `src/core/ros_px4_template_core/nodes/` and update that module's ROS 2 Interface docstring.
2. Add a row above (backticked name, type, owner).
3. Run `just sim` then `just check-topics` to confirm the topic shows up live.
