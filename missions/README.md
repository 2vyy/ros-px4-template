# Missions (launch recipes)

A **mission** here is a launch composition + param overlay, not a YAML file. Paths live in `config/paths/`. Profiles live in `config/params/overlays/`.

## Layout

```
missions/
  inspect/
    launch/inspect.launch.py   # sim + inspect_aruco world + vision + inspect overlay
```

## Adding a mission

1. `config/paths/<route>.yaml` — ENU points only.
2. `config/params/overlays/<name>.yaml` — `path_file`, `enable_marker_hover`, tolerances.
3. `missions/<name>/launch/<name>.launch.py` — include `sim_full` or `hardware` with args.
4. Optional sim nodes in `px4_ros_sim/` (vision, sensors).
5. `tests/scenarios/` + `tests/capabilities.toml`.

## Pose backends

| Context | Publisher of `/drone/pose_enu` |
|---------|--------------------------------|
| `just sim` | `sim_pose_adapter` (Gazebo model pose → ENU) |
| hardware | `px4_pose_adapter` (PX4 local position → ENU) |

See [docs/MISSIONS.md](../docs/MISSIONS.md).
