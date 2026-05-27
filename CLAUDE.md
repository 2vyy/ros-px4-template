# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working in this repository.

## Essential commands

```bash
just                        # list all recipes
just setup                  # one-time: uv sync + rosdep + colcon build
just clone-px4-msgs         # one-time: clone src/px4_msgs at release/1.17

just check                  # lint + invariants + typecheck + unit tests (run before every commit)
just build                  # colcon build --symlink-install
just build-incremental      # rebuild only core packages (faster iteration)
just clean                  # rm build/ install/ log/

just preflight              # check paths, ports, px4_msgs branch, workspace — run before launching
just sim                    # full sim stack with Gazebo GUI
just sim-headless           # same, no Gazebo window (use for agents/CI)
just wait-ready             # block until rosbridge :9090 + /fmu/out/* topic are live
just sim-stop               # kill all sim processes + ros2 daemon stop
just clean-logs             # wipe *.jsonl + run_summary.json before a run
just e2e                    # full headless cycle: clean-logs, preflight, sim, wait-ready, all scenarios, merge-logs

just scenario 01_arm_takeoff        # run a live scenario (sim must be up)
just mark-capability arm_takeoff sim  # record a passing scenario
just capabilities           # show capability registry

just check-topics           # audit live topics vs docs/TOPICS.md (sim must be up)
just merge-logs             # produce logs/merged.jsonl + logs/run_summary.json
just tail-logs              # stream structured JSONL live

just lint                   # ruff check + format check
just fix                    # ruff autofix + format
just typecheck              # ty check (lib/, tests/unit/, tools/ only)
just test-unit              # pytest tests/unit/ -v (no ROS needed)
```

## Environment

Set `.env` before first use:

```bash
PX4_DIR=/path/to/PX4-Autopilot
ROS_SETUP=/opt/ros/jazzy/setup.bash
PX4_VERSION=v1.17.0
```

`justfile` sources `.env` automatically. Never run `just build` or `just sim` from PowerShell — Gazebo/PX4/ROS require a Linux shell.

On CachyOS (this machine): ROS Jazzy lives inside a distrobox container named `ubuntu`. All `just` recipes that need ROS must run inside it:
```bash
distrobox enter ubuntu -- bash -lc "cd ~/Projects/ros-px4-template && just <recipe>"
```
`just check` (offline: lint, unit tests) and `uv run` commands work on the host without entering distrobox.

## Architecture

```
sim/launch/sim_full.launch.py        # launches everything: Gazebo, PX4 SITL, XRCE, ROS nodes, rosbridge
hardware/launch/hardware.launch.py   # included by sim launch; also standalone for real FC
src/core/ros_px4_template_core/
  nodes/          # mission_manager, offboard_controller, px4_topic_relay, state_estimator
  lib/            # frame_transforms, mission_runtime, waypoint_mission, marker_target, StructuredLogger
  bridges/        # PX4 DDS communication glue
src/px4_ros_msgs/ # custom msgs: ControllerStatus, MissionStatus
src/px4_ros_sim/  # sim-only helpers (never imported from src/core)
src/px4_msgs/     # upstream PX4 micro XRCE defs — pinned to release/1.17, never edited
config/params/    # common.yaml, sim.yaml, hardware.yaml overlays
config/missions/  # YAML mission definitions (ENU meters)
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

Rosbridge WebSocket runs on port **9090** (started by `hardware.launch.py`, included in both `just sim` and `just hardware`). `ros-mcp-server` connects to this port — MCP tools are available when a sim session is running.

Check port: `nc -z 127.0.0.1 9090`

MCP config lives in `.cursor/mcp.json` (not repo root). Set `command` to the literal output of `which uvx` on the machine running rosbridge.

## Scenario test pattern

Scenarios in `tests/scenarios/` are standalone async scripts (not pytest). They use `_common.spin_until` + `PX4_QOS` and `sys.exit(0/1)`. Run via `just scenario <name>` (no `.py` suffix). After a scenario passes, record it: `just mark-capability <id> sim`.

## Logs

Each node writes `logs/<node>.jsonl` via `StructuredLogger`. `just sim` tees stdout to `logs/sim_<timestamp>.log`.

After a run: `just merge-logs` → read `logs/run_summary.json` first (error_count, event_timeline), then `logs/merged.jsonl` for detail.

Key grep patterns in `logs/merged.jsonl`: `PHASE_CHANGE`, `WAYPOINT_REACHED`, `ARM_COMMAND_SENT`, `"level":"ERROR"`.

## Code conventions

- New nodes: create under `nodes/`, add to `entry_points` in `src/core/setup.py`, add a `Node(...)` line in `hardware/launch/hardware.launch.py`.
- New lib: add to `src/core/ros_px4_template_core/lib/`, unit test in `tests/unit/`. Keep `rclpy`-free.
- New topics: update the node's ROS 2 Interface docstring AND add a row in `docs/TOPICS.md` (backtick the name). `just check-topics` enforces this.
- New mission phases: add `PHASE_*` constant and branch in `lib/mission_runtime.py`. Do not embed phase logic in `nodes/mission_manager.py`.
- New scenarios: `tests/scenarios/<NN>_<name>.py` + capability entry in `tests/capabilities.toml`.
- Always use `StructuredLogger` for agent-facing diagnostics. Call `self.slog.close()` from `destroy_node`.

## Common failure modes

| Symptom | Fix |
|---------|-----|
| `just sim` hangs at Gazebo | Check `.env` has correct `PX4_DIR`; try `just sim-headless` |
| No `/fmu/out/*` topics | XRCE not running; check `ss -ulnp \| grep 8888`; check `logs/sim_*.log` for XRCE handshake |
| Topics appear as `*_v1` only | `px4_topic_relay` not running; relaunch with `just sim` |
| Scenario arm fail | `gcs_heartbeat` starts at +12s; tweak `arm_delay_s` in `config/params/sim.yaml` |
| `colcon` errors after node move | `just clean && just build` (stale symlink-install entry points) |
| MCP not connecting | Confirm port 9090 open; `which uvx` path in `.cursor/mcp.json` must be absolute |
| Stale daemon between runs | Run `just sim-stop` before relaunching |

Full troubleshooting and operational notes: [AGENTS.md](AGENTS.md).
