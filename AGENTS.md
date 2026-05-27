# AGENTS.md

Operating notes for an AI agent driving this repo. Optimized for debugging, running `just` workflows across native / WSL / distrobox, and core feature work.

**README vs this file:** [README.md](README.md) is the project overview (stack, [runtime architecture](README.md#runtime-architecture), [project structure](README.md#project-structure), quick start, everyday commands). This file is the operational guide: invariants, verification tiers, logs, MCP, and failure modes. Read the README once for context; use the sections below day to day.

## Initial setup

Complete [README quick start](README.md#quick-start) (through `just sim` or `just hardware`). For MCP and rosbridge checks, see [docs/MCP.md](docs/MCP.md).

## Where to run

| Context | Rule |
|---------|------|
| Ubuntu 24.04 native | `just <recipe>` in a project shell with Jazzy on PATH |
| WSL | Open repo in WSL, then `just <recipe>` in a WSL shell |
| WSL fallback (repo on `C:\`, agent in PowerShell) | `wsl -d Ubuntu -- bash -lc 'cd ~/Projects/ros-px4-template && just <recipe>'` |
| Distrobox | `distrobox enter ubuntu -- bash -lc 'cd ~/Projects/ros-px4-template && just <recipe>'` |

Never run `just build`, `just sim`, or `colcon` from PowerShell or cmd. Gazebo, PX4 SITL, and `ros2 launch` need a Linux shell. If you are unsure of the context, run `uname -a` first.

## Invariants (do not break)

1. `src/` is sim and hardware blind. No imports from `sim/` or `hardware/` into `src/`.
2. Frames: [docs/FRAMES.md](docs/FRAMES.md). All `src/` code uses ENU; convert only at the PX4 boundary in `offboard_controller` and `mission_manager`.
3. Never edit files inside `PX4_DIR`. Gazebo worlds and models belong in `sim/worlds` and `sim/models`.
4. `src/px4_msgs` stays on branch `release/1.17`. Enforced by `tools/check_invariants.py`.
5. Pure logic in `lib/`, nodes in `nodes/`, PX4 specific glue in `bridges/`.
6. `sim/launch/sim_full.launch.py` is the full sim. `hardware/launch/hardware.launch.py` is rosbridge plus core nodes only, included by the sim launch with `config:=sim`.

## Tooling

| Layer | Tool | Notes |
|-------|------|-------|
| ROS build | `colcon` via `just build` | `--symlink-install`, `RelWithDebInfo` |
| Python env | `uv` | `uv sync --group dev` in `just setup` |
| Tasks | `just` | `just --list` is canonical, aliases: `s`=sim, `b`=build, `hw`=hardware, `l`=lint |
| Lint and format | `ruff` via `just lint` and `just fix` | Paths: `src/core src/px4_ros_sim tests tools sim hardware`. Excludes `src/px4_msgs` |
| Type check | `ty` via `just typecheck` | Only `src/core/ros_px4_template_core/lib`, `tests/unit`, `tools/`. Nodes are not type checked |
| Invariants | `just check-invariants` | Currently just px4_msgs branch check |
| Unit tests | `just test-unit` | `pytest tests/unit -v`, no ROS graph needed |

`just check` runs lint, invariants, typecheck, and unit tests in that order. Run this before every commit.

## Common `just` workflows

| Goal | Recipe |
|------|--------|
| Build the workspace | `just build` (or `just build-incremental` for core packages only) |
| Clean colcon outputs | `just clean` |
| Full sim with GUI | `just sim` |
| Headless full sim | `just sim-headless` (do not pass `headless=true` to `just sim`, it would parse as `world`) |
| Sim with vision and ArUco mission | `just sim-inspect` or `just demo-inspect` (background sim plus RViz) |
| Stop everything | `just sim-stop` (greedy pkill plus `ros2 daemon stop`) |
| Hardware launch | `just hardware port=/dev/ttyUSB0 baud=921600` |
| PX4 SITL standalone (no ROS) | `just sim-px4` |
| Bring up MicroXRCEAgent only | `just xrce` |
| Edit a Gazebo world | `just gazebo-edit world=<name>` |
| Echo mission status | `just mission-status` |
| Tail structured logs live | `just tail-logs` |
| Merge JSONL logs after a run | `just merge-logs` |
| RViz only (existing sim) | `just rviz` or `just rviz-inspect` |
| Validate live topic graph | `just check-topics` (sim must be up) |
| Run a scenario | `just scenario <name>` (filename in `tests/scenarios/`, no `.py`) |
| Record a capability | `just mark-capability <id> sim` |
| Show capability registry | `just capabilities` |
| Pre-launch checks | `just preflight` (ports, paths, px4_msgs branch, workspace built) |
| Wait for sim ready | `just wait-ready` (blocks until rosbridge :9090 + /fmu/out/* live) |
| Clean per-run JSONL | `just clean-logs` (wipe *.jsonl + run_summary.json before a run) |
| Full headless e2e | `just e2e` (clean-logs + preflight + headless sim + wait-ready + all scenarios + check-topics + merge-logs) |
| Clone `px4_msgs` (once) | `just clone-px4-msgs` |
| Update PX4 to env `PX4_VERSION` | `just update-px4` |

Sim positional args: `just sim [world] [model] [enable_vision] [headless]`. Defaults `default x500 false false`. Use the named recipes (`sim-headless`, `sim-inspect`, `demo-inspect`) instead of fiddling with positions.

## Verify (use in this order when something changed)

| Tier | Command | Needs |
|------|---------|-------|
| Fast | `just check` | Nothing running |
| Prereqs | `just preflight` | Nothing running (checks paths/ports) |
| Build | `just build` | Jazzy sourced (`source /opt/ros/jazzy/setup.bash`) |
| Graph | `just check-topics` | `just sim` running |
| Live | `just scenario 01_arm_takeoff` | Full sim |
| All-in-one | `just e2e` | `just build` done, ports free |
| Record | `just mark-capability <id> sim` | Scenario PASS |

`/clock` missing in a hardware-style launch is expected. Use `just sim` so the Gazebo clock bridge in `sim_full.launch.py` publishes `/clock`.

Capability registry: `tests/capabilities.toml`. `just capabilities` shows status. After a scenario passes in sim, run `just mark-capability <id> sim` to update `status` and `last_verified`.

## Reference

| Need | Where |
|------|-------|
| Stack, architecture diagram, repo layout | [README.md](README.md) |
| Frames and ENU/NED rules | [docs/FRAMES.md](docs/FRAMES.md) |
| Topic owners and types | [docs/TOPICS.md](docs/TOPICS.md) |
| MCP / rosbridge | [docs/MCP.md](docs/MCP.md). Config: `.cursor/mcp.json` |
| Mission phases and YAML schema | [docs/MISSIONS.md](docs/MISSIONS.md) |
| Node I/O | ROS 2 Interface block in `src/core/ros_px4_template_core/nodes/*.py` |
| Open ideas | [docs/BACKLOG.md](docs/BACKLOG.md) |

## Logs

Each node writes structured JSONL to `logs/<node>.jsonl` via `StructuredLogger`. `just sim` also tees stdout to `logs/sim_<timestamp>.log`.

After a run:

1. `just merge-logs` produces `logs/merged.jsonl` (dedup repeats, configurable with `--no-dedup` and `--collapse-min`) and `logs/run_summary.json`.
2. Read `logs/run_summary.json` first. It contains `error_count` and an `event_timeline` built from `EVENT` records.
3. Drop into `logs/merged.jsonl` only when you need a specific window or non-event detail.

Useful grep patterns (after `just merge-logs`):

```bash
grep PHASE_CHANGE      logs/merged.jsonl
grep WAYPOINT_REACHED  logs/merged.jsonl
grep MARKER_ACQUIRED   logs/merged.jsonl
grep ARM_COMMAND_SENT  logs/merged.jsonl
grep '"level":"ERROR"' logs/merged.jsonl
```

## MCP / rosbridge

- Rosbridge is on port 9090, started by `hardware.launch.py` (which `sim_full.launch.py` includes).
- Check the port: `nc -z 127.0.0.1 9090`.
- `command` in `.cursor/mcp.json` must be the literal output of `which uvx` on the same OS that runs rosbridge. No `${userHome}`.
- Cross-OS gotcha: Windows IDE pointing at WSL rosbridge does not work. Run both in WSL.

## If X fails

| X | Check |
|---|-------|
| `just build` | `log/latest_build/`; confirm `src/px4_msgs` is on `release/1.17` (`just check-invariants`); confirm `source /opt/ros/jazzy/setup.bash` happened |
| `just sim` hangs at Gazebo | `.env` has correct `PX4_DIR`; `${PX4_DIR}/build/px4_sitl_default/bin/px4` exists; on WSL confirm WSLg for GUI; try `just sim-headless` |
| No `/fmu/out/*` topics | PX4 SITL is running and MicroXRCEAgent is on UDP 8888 (`ss -ulnp | grep 8888`); check `logs/sim_*.log` for XRCE handshake |
| `/fmu/out/vehicle_local_position` exists as `_v1` only | `px4_topic_relay` is not running; relaunch with `just sim` (it includes the hardware launch which spawns the relay) |
| Scenario arm fail | `gcs_heartbeat` runs at +12s in `sim_full.launch.py`; tweak `offboard_controller.arm_delay_s` in `config/params/sim.yaml` if PX4 boot is slow |
| Mission stuck in `wait_arm_altitude` | `takeoff_altitude_m` exceeds achievable climb in time; ensure `controller_status.armed` is `true` and ENU z is at or above `takeoff_altitude_m` |
| Mission never enters `hover_marker` | `enable_vision:=true` needed; `/vision/marker_pose` valid; `marker.acquire_frames` consecutive frames must be hit |
| `just check-topics` reports missing | Topic backticked in `docs/TOPICS.md` but never published; either fix the node or remove from the manifest |
| MCP errors | See [docs/MCP.md](docs/MCP.md); confirm port 9090 open and `which uvx` path correct for the OS hosting rosbridge |
| Stale ROS daemon between runs | `just sim-stop` (kills sim processes plus `ros2 daemon stop`) before relaunching |
| `colcon` errors after a node move | `just clean && just build`; symlink install caches stale entry points otherwise |

## Code changes

- When adding or changing a topic: update the node's ROS 2 Interface docstring AND the row in [docs/TOPICS.md](docs/TOPICS.md). `just check-topics` will fail otherwise once the sim is up.
- When adding a new node:
  1. Create it under `src/core/ros_px4_template_core/nodes/`.
  2. Add an entry to `entry_points["console_scripts"]` in `src/core/setup.py`.
  3. Add a `Node(...)` line in `hardware/launch/hardware.launch.py` so both sim and hardware launches pick it up.
  4. `just build` then verify with `ros2 node list`.
- New libraries go in `src/core/ros_px4_template_core/lib/`. Add unit tests in `tests/unit/`. `lib/` must remain `rclpy` free where possible (see `StructuredLogger` Protocol pattern).
- Always use `StructuredLogger` for agent-facing diagnostics. Call `self.slog.close()` from `destroy_node`.
- New mission phases go in `lib/mission_runtime.py` (add a `PHASE_*` constant and a branch in `tick`). Do not embed phase logic in `nodes/mission_manager.py`.
- New scenarios go in `tests/scenarios/<NN>_<name>.py` using `_common.spin_until` and `PX4_QOS`. Add a capability entry in `tests/capabilities.toml`.
- Do not commit `.env`, `logs/`, `build/`, `install/`, or `log/`.

## House style

- Match the README's terse, table-heavy tone.
- No em dashes, no Unicode arrows. Use `to`, `becomes`, plain hyphens, or punctuation.
- Prefer linking back to a doc over duplicating it.
