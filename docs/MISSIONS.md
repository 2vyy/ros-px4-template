# Missions

Missions are a phase string plus one `tick()` in `ros_px4_template_core.lib.mission_runtime`, not a class-per-state FSM. Mission YAML is loaded by `waypoint_mission.load_mission_yaml`. Phases live in `mission_runtime`. `mission_manager` (the node) wires both to ROS.

## Inspect ArUco demo

```bash
just demo-inspect      # sim + vision in background, RViz in foreground
just sim-inspect       # sim only (vision enabled, no RViz)
just rviz-inspect      # RViz against an already-running sim
```

Mission config: `config/missions/inspect_aruco.yaml`. Waypoints are ENU `(x, y, z)`. After the path completes, hover above the ArUco marker while `/vision/marker_pose` is valid.

### Phases

| Phase | Meaning |
|-------|---------|
| `wait_arm_altitude` | Hold first waypoint until `offboard_controller` reports armed and ENU altitude is at or above `takeoff_altitude_m` |
| `follow_path` | Step through waypoints, requiring tolerance plus hold time on each |
| `hover_marker` | Track the marker plus offset for `hold_duration_s` |
| `done` | Mission complete |

Transitions and event names (`PHASE_CHANGE`, `WAYPOINT_REACHED`, `MARKER_ACQUIRED`, `MARKER_LOST`, `MISSION_DONE`) come from `mission_runtime.tick`.

### YAML schema

```yaml
frame_id: map
defaults:
  tolerance_m: 0.4
  hold_s: 2.0
marker:                      # optional
  hold_offset_enu: {x: 0.0, y: 0.0, z: 1.5}
  hold_duration_s: 30.0
  lost_timeout_s: 1.0
  acquire_frames: 5
waypoints:
  - {x: 0.0, y: 0.0, z: 3.0}
  - {x: 5.0, y: 0.0, z: 3.0}
```

`marker.acquire_frames` is the number of consecutive valid frames needed before transitioning into `hover_marker`. `marker.lost_timeout_s` debounces the `MARKER_LOST` event after the marker drops out.

### Topics

| Topic | Type |
|-------|------|
| `/drone/mission_status` | `px4_ros_msgs/MissionStatus` |
| `/drone/mission_markers` | `visualization_msgs/MarkerArray` |
| `/vision/marker_pose` | `geometry_msgs/PoseStamped` (sim detector) |

Publishers and subscribers: [docs/TOPICS.md](TOPICS.md).

### Params

`config/params/sim.yaml` sets `mission_manager.mission_file`, `tick_rate_hz`, `takeoff_altitude_m`, and the `offboard_controller` arming and prestream timings. Common defaults live in `config/params/common.yaml`.

### Logs

Live: `just tail-logs`.

After a run:

```bash
grep PHASE_CHANGE logs/merged.jsonl
grep MARKER_ACQUIRED logs/merged.jsonl
grep WAYPOINT_REACHED logs/merged.jsonl
```

Post-run summary: [AGENTS.md §MCP / logs](../AGENTS.md#mcp--logs).

### Scenario coverage

| Scenario | Pass condition |
|----------|----------------|
| `tests/scenarios/inspect_aruco.py` | Mission reaches `hover_marker` or `done` before timeout |
| `tests/scenarios/03_waypoint.py` | Mission phase reaches `done` |

ArUco vision is sim-only in v1 (`px4_ros_sim/aruco_detector`). Hardware can publish the same `/vision/marker_pose` contract later without changes to `mission_manager`.
