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
| Tasks | `just` | `just --list` is canonical. Wraps `tasks.py` which exposes 5 workflows. |
| Quality gateway | `just check` | Automatically formats, lint-fixes, typechecks, builds workspace, and runs unit tests |
| Simulation & Run | `just sim [mode]` | Automatically builds workspace first. Modes: `gui`, `headless`, `bg`, `px4`, `edit`, `hardware`, `stop` |
| Verification suite | `just test [type]` | Automatically builds workspace first. Types: `unit`, `scenario <name>`, `e2e` |
| Forensic toolkit | `just log [subcmd]` | Merges/queries logs, checks status/topics, manages capabilities |

`just check` runs lint, invariants, typecheck, and unit tests in that order. Run this before every commit.

## Common `just` workflows

| Goal | Recipe |
|------|--------|
| One-time workspace setup | `just setup` |
| Quality checks + Build | `just check` |
| Clean build/logs | `just clean` |
| Full sim with GUI | `just sim` (or `just sim headless` / `just sim bg`) |
| PX4 SITL standalone (no ROS) | `just sim px4` |
| Edit a Gazebo world | `just sim edit world=<name>` |
| Connect to Serial Hardware FC | `just sim hardware port=/dev/ttyUSB0 baud=921600` |
| Stop everything | `just sim stop` (kills Gazebo, PX4, and ROS nodes) |
| Run unit tests | `just test` (or `just test unit`) |
| Run a live scenario | `just test scenario --arg <name>` (e.g. `01_arm_takeoff`) |
| Run headless E2E cycle | `just test e2e` |
| Tail structured logs live | `just log tail` |
| View live workspace status | `just log status` |
| Validate live topic graph | `just log topics` |
| Show capability registry | `just log cap show` |
| Record verified capability | `just log cap mark <id> sim` |

Sim positional args: `just sim [mode] [world] [model] [vision]`. Defaults: `gui`, `default`, `x500`, `false`. Modes: `gui`, `headless`, `bg`, `px4`, `inspect`.

## Verify (use in this order when something changed)

| Tier | Command | Needs |
|------|---------|-------|
| Fast | `just check` | Nothing running |
| Graph | `just log topics` | `just sim` running |
| Live | `just test scenario --arg 01_arm_takeoff` | Full sim |
| All-in-one | `just test e2e` | `just setup` done, ports free |
| Record | `just log cap mark <id> sim` | Scenario PASS |

`/clock` missing in a hardware-style launch is expected. Use `just sim` so the Gazebo clock bridge in `sim_full.launch.py` publishes `/clock`.

Capability registry: `tests/capabilities.toml`. `just log cap show` shows status. After a scenario passes in sim, run `just log cap mark <id> sim` to update `status` and `last_verified`.

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

Each node writes structured JSONL to `logs/<node>.jsonl`. After a run, the merge step compresses
high-frequency telemetry into `logs/merged.log` (human-readable) and `logs/run_summary.json`
(pre-digested digest). Both are small enough to read directly.

1. **Start here**: `just log summary` — error count, collapsed event timeline, error fingerprints.
2. **Search**: `rg PHASE_CHANGE logs/merged.log`, `rg ERROR logs/merged.log`, etc. The merge step
   already removed telemetry noise — `rg` on the merged log is the right tool.
3. **Time window**: `just log window --t <timestamp>` — slice ±5s around a specific event time.
4. **Per-node raw data**: `just log node <name>` — last 50 lines from one node's unmerged JSONL.
5. **Live tail**: `just log tail` — stream new records during a running sim.

## MCP / rosbridge

- Rosbridge is on port 9090, started by `hardware.launch.py` (which `sim_full.launch.py` includes).
- Check the port: `nc -z 127.0.0.1 9090`.
- `command` in `.cursor/mcp.json` must be the literal output of `which uvx` on the same OS that runs rosbridge. No `${userHome}`.
- Cross-OS gotcha: Windows IDE pointing at WSL rosbridge does not work. Run both in WSL.

## If X fails

| X | Check |
|---|-------|
| `just check` | `log/latest_build/`; confirm `src/px4_msgs` is on `release/1.17` (`just check`); confirm `source /opt/ros/jazzy/setup.bash` happened |
| `just sim` hangs at Gazebo | `.env` has correct `PX4_DIR`; `${PX4_DIR}/build/px4_sitl_default/bin/px4` exists; on WSL confirm WSLg for GUI; try `just sim headless` |
| No `/fmu/out/*` topics | PX4 SITL is running and MicroXRCEAgent is on UDP 8888 (`ss -ulnp | grep 8888`); check `logs/sim_*.log` for XRCE handshake |
| `/fmu/out/vehicle_local_position` exists as `_v1` only | `px4_topic_relay` is not running; relaunch with `just sim` (it includes the hardware launch which spawns the relay) |
| Scenario arm fail | `gcs_heartbeat` starts at t=0 and sets `COM_ARM_WO_GPS=1` immediately; `arm_delay_s` in `config/params/sim.yaml` only needs to cover XRCE handshake time (default 5s); increase it if PX4 boot is slow |
| Mission stuck in `wait_arm_altitude` | `takeoff_altitude_m` exceeds achievable climb in time; ensure `controller_status.armed` is `true` and ENU z is at or above `takeoff_altitude_m` |
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
  4. `just check` then verify with `ros2 node list`.
- New libraries go in `src/core/ros_px4_template_core/lib/`. Add unit tests in `tests/unit/`. `lib/` must remain `rclpy` free where possible (see `StructuredLogger` Protocol pattern).
- Always use `StructuredLogger` for agent-facing diagnostics. Call `self.slog.close()` from `destroy_node`.
- New mission phases go in `lib/mission_runtime.py` (add a `PHASE_*` constant and a branch in `tick`). Do not embed phase logic in `nodes/mission_manager.py`.
- New scenarios go in `tests/scenarios/<NN>_<name>.py` using `_common.spin_until` and `PX4_QOS`. Add a capability entry in `tests/capabilities.toml`.
- Do not commit `.env`, `logs/`, `build/`, `install/`, or `log/`.

## House style

- Match the README's terse, table-heavy tone.
- No em dashes, no Unicode arrows. Use `to`, `becomes`, plain hyphens, or punctuation.
- Prefer linking back to a doc over duplicating it.
