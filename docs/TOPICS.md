# Topic manifest

Validated against a running stack with `just log topics`. The checker greps backtick-quoted topic names (e.g. the rows below) out of this file and confirms each one appears in `ros2 topic list`, so keep topic names backticked.

## PX4 versioned topics

PX4 1.17 with uXRCE-DDS appends `_v1` to any message carrying `MESSAGE_VERSION` (e.g. `VehicleLocalPosition`, `VehicleStatus`). Core nodes subscribe to those `_v1` names directly; sim and hardware run the same firmware and publish them identically, so no rename shim is needed.

## Topics

| Topic | Type | Dir | Owner |
|-------|------|-----|-------|
| `/clock` | `rosgraph_msgs/msg/Clock` | pub | clock_bridge in `sim/launch/sim_full.launch.py` |
| `/fmu/out/vehicle_local_position_v1` | `px4_msgs/msg/VehicleLocalPosition` | pub | PX4 uXRCE-DDS bridge |
| `/fmu/out/vehicle_status_v1` | `px4_msgs/msg/VehicleStatus` | pub | PX4 uXRCE-DDS bridge |
| `/fmu/in/trajectory_setpoint` | `px4_msgs/msg/TrajectorySetpoint` | pub | `offboard_controller` |
| `/fmu/in/offboard_control_mode` | `px4_msgs/msg/OffboardControlMode` | pub | `offboard_controller` |
| `/fmu/in/vehicle_command` | `px4_msgs/msg/VehicleCommand` | pub | `offboard_controller` |
| `/drone/odom` | `nav_msgs/msg/Odometry` | pub | `position_node` (anchored-ENU SoT pose+twist) |
| `/drone/local_origin` | `geometry_msgs/msg/Vector3Stamped` | pub | `position_node` (latched effective NED origin) |
| `/drone/target_pose` | `geometry_msgs/msg/PoseStamped` | pub | `mission_manager` |
| `/drone/controller_status` | `px4_ros_msgs/msg/ControllerStatus` | pub | `offboard_controller` |
| `/drone/mission_status` | `px4_ros_msgs/msg/MissionStatus` | pub | `mission_manager` |
| `/drone/mission_markers` | `visualization_msgs/msg/MarkerArray` | pub | `mission_manager` (RViz waypoint visualization) |
| `/drone/marker_detection` | `px4_ros_msgs/msg/MarkerDetection` | pub (vision) | `aruco_pose_publisher` |
| `/drone/pose_override` | `geometry_msgs/msg/PoseStamped` | pub (vision) | `marker_localizer` (known-marker relocalization fix) |

### Subscriptions

| Topic | Subscribers |
|-------|-------------|
| `/fmu/out/vehicle_local_position_v1` | `position_node` |
| `/drone/odom` | `offboard_controller`, `mission_manager` |
| `/drone/local_origin` | `offboard_controller` |
| `/fmu/out/vehicle_status_v1` | `offboard_controller` |
| `/drone/target_pose` | `offboard_controller` |
| `/drone/controller_status` | `mission_manager` |
| `/drone/marker_detection` | `mission_manager`, `marker_localizer` |
| `/drone/pose_override` | `position_node` (applied when fresh and within jump bound) |

## QoS

- PX4 topics (`/fmu/*`): `BEST_EFFORT` reliability, `TRANSIENT_LOCAL` durability, `KEEP_LAST` depth 10. Defined in each node and as `PX4_QOS` in `tests/scenarios/_common.py`.
- `/drone/odom`: `RELIABLE`. Single source of truth published by `position_node` from PX4's local-position estimate (anchored ENU), in both sim and hardware. `/drone/local_origin`: latched (`TRANSIENT_LOCAL`) effective NED setpoint origin.
- `/drone/marker_detection`: `RELIABLE`, `KEEP_LAST` depth 10.
- Other `/drone/*` status and setpoint topics: `RELIABLE`, `KEEP_LAST` depth 10.
- `/drone/target_pose` orientation is an optional-yaw contract, not a real attitude: the all-zero quaternion means "yaw omitted" (PX4 holds current heading); any other finite, near-unit quaternion is a commanded ENU yaw. See [docs/MISSIONS.md](MISSIONS.md#commanding-yaw) and `lib/target_pose.py`.

A `(vision)` suffix on the Dir marks a topic published only under
`--vision aruco`; `just log topics` skips its presence check unless run with
`--vision`.

## Adding a topic

1. Publish or subscribe in a node under `src/core/ros_px4_template_core/nodes/` and update that module's ROS 2 Interface docstring.
2. Add a row above (backticked name, type, owner).
3. Run `just sim` then `just log topics` to confirm the topic shows up live.

The Type and Dir columns are enforced by `just log topics` against the live
graph, so they must match the node's actual publisher/subscriber and message
type.
