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
| Workspace Setup | `uv run tasks.py setup` | `just setup` clones dependencies, runs uv sync and rosdep |
| Tasks | `just` | `just --list` is canonical. Wraps `tasks.py` |
| Quality gateway | `just check` | Automatically formats, lint-fixes, typechecks, builds workspace, and runs unit tests |
| Simulation & Run | `just sim [mode]` | Automatically builds workspace first. Modes: `headless` (default), `gui`, `bg` (blocks until ready), `stop`, `kill` |
| Real Hardware | `just hw` | Connects to hardware serial flight controller |
| Verification suite | `just test [type]` / `just scenario <name>` | Automatically builds workspace first. Types: `unit`, `e2e` |
| Forensic toolkit | `just log [subcmd]` | Observability helper: `summary`, `tail`, `topics` |
| Capabilities | `just cap [subcmd]` | Exposes verified capabilities: `show`, `mark` |

`just check` runs lint, invariants, typecheck, and unit tests in that order. Run this before every commit.

## Common `just` workflows

| Goal | Recipe |
|------|--------|
| One-time workspace setup | `just setup` |
| Quality checks + Build | `just check` |
| Clean build/logs | `just clean` |
| Headless simulation | `just sim` (or `just sim gui` / `just sim bg`) |
| Connect to Serial Hardware FC | `just hw --port /dev/ttyUSB0 --baud 921600` |
| Stop everything | `just sim stop` (kills ROS/PX4, keeps Gazebo warm) |
| Full teardown (cold start) | `just sim kill` (kills everything including Gazebo) |
| Run unit tests | `just test` |
| Run a live scenario | `just scenario <name>` (e.g. `just scenario 01_arm_takeoff`) |
| Run headless E2E cycle | `just test e2e` |
| Tail structured logs live | `just log tail` |
| View live workspace status | `just status` |
| Validate live topic graph | `just log topics` |
| Show capability registry | `just cap show` |
| Record verified capability | `just cap mark <id> sim` |

Sim arguments: `just sim [mode] [--world <world>] [--model <model>] [--vision <vision>]`. Defaults: `headless`, `default`, `x500`, `false`. Modes: `headless`, `gui`, `bg`, `inspect`.

## Verify (use in this order when something changed)

| Tier | Command | Needs |
|------|---------|-------|
| Fast | `just check` | Nothing running |
| Graph | `just log topics` | `just sim` running |
| Live | `just scenario 01_arm_takeoff` | Full sim |
| All-in-one | `just test e2e` | `just setup` done, ports free |
| Record | `just cap mark <id> sim` | Scenario PASS |

`/clock` missing in a hardware-style launch is expected. Use `just sim` so the Gazebo clock bridge in `sim_full.launch.py` publishes `/clock`.

Capability registry: `tests/capabilities.toml`. `just cap show` shows status. After a scenario passes in sim, run `just cap mark <id> sim` to update `status` and `last_verified`.

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

## Logs (Agent Query Workflow)

All processes (our nodes plus PX4 / Gazebo / XRCE) stream to one session log, `logs/latest.log`, in logfmt: every line is `t=<rel_s> src=<source> ...`. There are no per-node `*.jsonl` files and no `jq` step.

1. **Grep it directly**: `rg src=px4 logs/latest.log` (one source), `rg event= logs/latest.log` (state transitions), `rg ERROR logs/latest.log`, `rg -C 5 "t=42\." logs/latest.log` (everything around t=42). Field extraction needs no tool: `rg event=WAYPOINT_REACHED logs/latest.log | grep -o "err_m=[0-9.]*"`.
2. **Arc summary**: `just log summary` (re)generates and prints `logs/latest_summary.json` (run arc, errors, per-scenario pass/fail). E2E prints it automatically at the end.
3. **Live tail**: `just log tail` follows `logs/latest.log`.

Consecutive-identical lines are collapsed to one with a trailing `(xN)`; nothing else is filtered, so a smoking gun is never hidden.

## MCP / rosbridge

- Rosbridge is on port 9090, started by `hardware.launch.py` (which `sim_full.launch.py` includes).
- Check the port: `nc -z 127.0.0.1 9090`.
- `command` in `.cursor/mcp.json` must be the literal output of `which uvx` on the same OS that runs rosbridge. No `${userHome}`.
- Cross-OS gotcha: Windows IDE pointing at WSL rosbridge does not work. Run both in WSL.

## If X fails

| X | Check |
|---|-------|
| `just check` | `log/latest_build/`; confirm `src/px4_msgs` is on `release/1.17` (`just check`); ensure ROS is sourced or distrobox is available (handled automatically by `justfile` now) |
| `just sim` hangs at Gazebo | `.env` has correct `PX4_DIR`; `${PX4_DIR}/build/px4_sitl_default/bin/px4` exists; on WSL confirm WSLg for GUI; try `just sim headless` |
| No `/fmu/out/*` topics | PX4 SITL is running and MicroXRCEAgent is on UDP 8888 (`ss -ulnp | grep 8888`); check `logs/latest.log` (`rg src=xrce`) for the XRCE handshake |
| `/fmu/out/vehicle_local_position` exists as `_v1` only | `px4_topic_relay` is not running; relaunch with `just sim bg` (it includes the hardware launch which spawns the relay) |
| Scenario arm fail | `gcs_heartbeat` via `uv run`; `just sim stop` kills MicroXRCEAgent (session key rotates each launch); `arm_delay_s` in `config/params/sim.yaml` (default 3s) |
| Mission stuck in `wait_arm_altitude` | Gate: effective ENU z (`max(pose, controller alt)`) >= `takeoff_altitude_m - takeoff_altitude_tolerance_m`. In sim check `sim_pose_adapter` / Gazebo pose; on hardware check `px4_pose_adapter` for `First pose published` (`xy_valid` and `z_valid`). |
| Mission never enters `hover_marker` | `enable_vision:=true` needed; `/vision/marker_pose` valid; `marker.acquire_frames` consecutive frames must be hit |
| `just log topics` reports missing | Topic backticked in `docs/TOPICS.md` but never published; either fix the node or remove from the manifest |
| MCP errors | See [docs/MCP.md](docs/MCP.md); confirm port 9090 open and `which uvx` path correct for the OS hosting rosbridge |
| Stale ROS daemon between runs | `just sim stop` (kills sim processes plus `ros2 daemon stop`) before relaunching |
| `colcon` errors after a node move | `just clean && just check`; symlink install caches stale entry points otherwise |

## Code changes

- When adding or changing a topic: update the node's ROS 2 Interface docstring AND the row in [docs/TOPICS.md](docs/TOPICS.md). `just log topics` will fail otherwise once the sim is up.
- When adding a new node:
  1. Create it under `src/core/ros_px4_template_core/nodes/`.
  2. Add an entry to `entry_points["console_scripts"]` in `src/core/setup.py`.
  3. Add a `Node(...)` line in `hardware/launch/hardware.launch.py` so both sim and hardware launches pick it up.
  4. `just check` then verify with `just status` or `ros2 node list`.
- New libraries go in `src/core/ros_px4_template_core/lib/`. Add unit tests in `tests/unit/`. `lib/` must remain `rclpy` free where possible (see `StructuredLogger` Protocol pattern).
- Always use `StructuredLogger` for agent-facing diagnostics. Call `self.slog.close()` from `destroy_node`.
- New mission phases go in `lib/mission_runtime.py` (add a `PHASE_*` constant and a branch in `tick`). Do not embed phase logic in `nodes/mission_manager.py`.
- New scenarios go in `tests/scenarios/<NN>_<name>.py` using `_common.spin_until` and `PX4_QOS`. Add a capability entry in `tests/capabilities.toml` and record via `just cap mark <id> sim` when passing.
- Do not commit `.env`, `logs/`, `build/`, `install/`, or `log/`.

## House style

- Match the README's terse, table-heavy tone.
- No em dashes, no Unicode arrows. Use `to`, `becomes`, plain hyphens, or punctuation.
- Prefer linking back to a doc over duplicating it.
