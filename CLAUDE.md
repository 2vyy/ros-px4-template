# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working in this repository.

## Essential commands

All tasks are orchestrated by a unified Python runner `tasks.py` and wrapped by `just` to ensure proper ROS environment sourcing.

```bash
just                        # list all workflows
just setup                  # one-time: auto-clones px4_msgs + uv sync + rosdep
just check                  # lint + format + invariants + typecheck + build + unit tests

just sim                    # simulation with Gazebo GUI (automatically compiles first)
just sim headless           # same, no Gazebo GUI window
just sim bg                 # run headless simulation in the background (idempotent)
just px4                    # run PX4 SITL standalone (no ROS)
just sim edit               # open Gazebo Harmonic world editor
just hw                     # connect to serial hardware flight controller
just sim stop               # kill ROS and PX4 processes (keeps Gazebo warm)
just sim kill               # full teardown (kills everything including Gazebo)

just test                   # run pytest unit tests (automatically compiles first)
just scenario <name>        # run a live scenario directly (e.g. just scenario 01_arm_takeoff)
just test e2e               # run full E2E headless verification cycle

just status                 # show JSON status snapshot of running simulation
just cap show               # show capability registry status
just cap mark <c> <p>       # mark capability as verified (e.g. just cap mark arm_takeoff sim)

just log tail               # stream/watch structured logs live
just log merge              # manually trigger merge of structured logs
just log topics             # audit live topics vs docs/TOPICS.md

# After merge, search logs directly — merged.log is small and already deduped:
rg PHASE_CHANGE logs/merged.log
rg ERROR logs/merged.log
rg -C 10 "\[\s*42\." logs/merged.log   # query logs around relative time t=42
```

## Environment

Set `.env` before first use:

```bash
PX4_DIR=/path/to/PX4-Autopilot
ROS_SETUP=/opt/ros/jazzy/setup.bash
PX4_VERSION=v1.17.0
```

`justfile` sources `.env` automatically. Never run `just build` or `just sim` from PowerShell — Gazebo/PX4/ROS require a Linux shell.

On CachyOS (this machine): ROS Jazzy lives inside a distrobox container named `ubuntu`. `just` automatically delegates to distrobox if `ROS_SETUP` is missing on the host, but you can also run commands inside it manually:
```bash
distrobox enter ubuntu -- bash -lc "cd ~/Projects/ros-px4-template && just <recipe>"
```
`just check` (offline: lint, unit tests) and `uv run` commands work on the host without entering distrobox.

## Architecture

```
sim/launch/sim_full.launch.py        # launches everything: Gazebo, PX4 SITL, XRCE, ROS nodes, rosbridge
hardware/launch/hardware.launch.py   # included by sim launch; also standalone for real FC
src/core/ros_px4_template_core/
  nodes/          # mission_manager, offboard_controller, px4_topic_relay, px4_pose_adapter
  lib/            # frame_transforms, mission_runtime, waypoint_mission, marker_target, StructuredLogger
  bridges/        # PX4 DDS communication glue
src/px4_ros_msgs/ # custom msgs: ControllerStatus, MissionStatus
src/px4_ros_sim/  # sim-only helpers (never imported from src/core)
src/px4_msgs/     # upstream PX4 micro XRCE defs — pinned to release/1.17, never edited
config/params/    # common.yaml, sim.yaml, hardware.yaml overlays
config/paths/     # ENU waypoint lists; mission profiles in config/params/
tests/
  unit/           # pure Python, no ROS graph
  scenarios/      # live acceptance scripts run via `just scenario <name>`
  capabilities.toml  # verified capability registry
tools/            # log_merger, check_topics, check_invariants, capabilities CLI
docs/             # FRAMES.md, TOPICS.md, MCP.md, MISSIONS.md, BACKLOG.md
```

**Control flow:** `mission_manager` emits ENU target poses → `offboard_controller` converts ENU to PX4 NED and sends setpoints → MicroXRCEAgent relays to PX4 SITL → Gazebo.

**Topic relay:** PX4 1.17 publishes `*_v1` topics. `px4_topic_relay` remaps them to the legacy names (`/fmu/out/vehicle_local_position`, `/fmu/out/vehicle_status`) that core nodes subscribe to.

## Invariants

1. `src/` is sim/hardware blind. No imports from `sim/` or `hardware/` into `src/`.
2. All internal coordinates are ENU (ROS REP-103). NED conversion happens only in `offboard_controller` and `mission_manager`.
3. Never edit files inside `PX4_DIR`. Worlds and models go in `sim/worlds` and `sim/models`.
4. `src/px4_msgs` stays on branch `release/1.17` (enforced by `just check-invariants`).
5. Pure logic in `lib/`; nodes in `nodes/`; PX4 glue in `bridges/`. `lib/` must stay `rclpy`-free where possible (see `StructuredLogger` Protocol pattern).

## Live testing with MCP / rosbridge

Rosbridge WebSocket runs on port **9090** (started by `hardware.launch.py`, included in both `just sim` and `just hw`). `ros-mcp-server` connects to this port — MCP tools are available when a sim session is running.

Check port: `nc -z 127.0.0.1 9090`

MCP config lives in `.cursor/mcp.json` (not repo root). Set `command` to the literal output of `which uvx` on the machine running rosbridge.

## Scenario test pattern

Scenarios in `tests/scenarios/` are standalone async scripts (not pytest). They use `_common.spin_until` + `PX4_QOS` and `sys.exit(0/1)`. Run via `just scenario <name>` (no `.py` suffix). After a scenario passes, record it: `just cap mark <id> sim`.

## Logs

Each node writes `logs/<node>.jsonl` via `StructuredLogger`. `just sim` tees stdout to `logs/sim_<timestamp>.log`.

After a run, the merge step (`just log merge`) compresses telemetry noise — `logs/merged.log` is small and safe to search directly with `rg`.
- `rg ERROR logs/merged.log` — errors
- `rg -C 10 "\[\s*42\." logs/merged.log` — search around relative time t=42
- `rg -C 3 <pattern> logs/merged.log` — search with context

## Code conventions

- New nodes: create under `nodes/`, add to `entry_points` in `src/core/setup.py`, add a `Node(...)` line in `hardware/launch/hardware.launch.py`.
- New lib: add to `src/core/ros_px4_template_core/lib/`, unit test in `tests/unit/`. Keep `rclpy`-free.
- New topics: update the node's ROS 2 Interface docstring AND add a row in `docs/TOPICS.md` (backtick the name). `just log topics` enforces this.
- New mission phases: add `PHASE_*` constant and branch in `lib/mission_runtime.py`. Do not embed phase logic in `nodes/mission_manager.py`.
- New scenarios: `tests/scenarios/<NN>_<name>.py` + capability entry in `tests/capabilities.toml`.
- Always use `StructuredLogger` for agent-facing diagnostics. Call `self.slog.close()` from `destroy_node`.

## Common failure modes

| Symptom | Fix |
|---------|-----|
| `just sim` hangs at Gazebo | Check `.env` has correct `PX4_DIR`; try `just sim headless` |
| No `/fmu/out/*` topics | XRCE not running; check `ss -ulnp \| grep 8888`; check `logs/sim_*.log` for XRCE handshake |
| Topics appear as `*_v1` only | `px4_topic_relay` not running; relaunch with `just sim` |
| Scenario arm fail | `gcs_heartbeat` uses `uv run` (needs pymavlink); stale MicroXRCEAgent after warm stop breaks XRCE (restarted each launch); tweak `arm_delay_s` in `config/params/sim.yaml` |
| `colcon` errors after node move | `just clean && just check` (stale symlink-install entry points) |
| MCP not connecting | Confirm port 9090 open; `which uvx` path in `.cursor/mcp.json` must be absolute |
| Stale daemon between runs | Run `just sim stop` before relaunching |

Full troubleshooting and operational notes: [AGENTS.md](AGENTS.md).
