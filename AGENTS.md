# AGENTS.md

Operating notes for an AI agent driving this repo. Optimized for debugging, running `just` workflows across native / WSL / distrobox, and core feature work.

**README vs this file:** [README.md](README.md) is the project overview (stack, [runtime architecture](README.md#runtime-architecture), [project structure](README.md#project-structure), quick start, everyday commands). This file is the operational guide: invariants, verification tiers, logs, MCP, and failure modes. Read the README once for context; use the sections below day to day.

## Initial setup

Complete [README quick start](README.md#quick-start) (through `just sim` or `just hw`). For MCP and rosbridge checks, see [docs/MCP.md](docs/MCP.md).

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
5. Pure logic in `lib/`, nodes in `src/core/ros_px4_template_core/nodes/`. ENU/NED conversion stays at the PX4 boundary in `src/core/ros_px4_template_core/nodes/offboard_controller.py` and `src/core/ros_px4_template_core/nodes/mission_manager.py`.
6. `sim/launch/sim_full.launch.py` is the full sim. `hardware/launch/hardware.launch.py` is rosbridge plus core nodes only, included by the sim launch with `config:=sim`.

## Tooling

| Layer | Tool | Notes |
|-------|------|-------|
| Workspace Setup | `uv run tasks.py setup` | `just setup` clones dependencies, runs uv sync and rosdep |
| Tasks | `just` | `just --list` is canonical. Wraps `tasks.py` |
| Quality gateway | `just check` | Automatically formats, lint-fixes, typechecks, builds workspace, and runs unit tests |
| Simulation & Run | `just sim [flags]` | Smart-builds, boots detached, waits till ready, prints verdict, returns. Never holds the terminal. Flags: `--gui`, `--world`, `--model`, `--vision`, `--overlay`, `--record`, `--no-build`, `--timeout` |
| Real Hardware | `just hw [flags]` | Same detached + verdict contract for the serial flight controller |
| Lifecycle | `just stop` | Exhaustive cold teardown; no process survives |
| Verification suite | `just test [type]` / `just scenario <name>` | Smart-builds first. Types: `unit`, `e2e`. e2e blocks by default (captures terminal, ends with PASS/FAIL); `--detach` runs it in the background, poll with `just e2e-status` |
| Forensic toolkit | `just log [subcmd]` | Observability helper: `summary`, `tail`, `topics` |
| Claims ladder | `just cap [subcmd]` | Derived capability rungs: `show`, `plan`, `record` |

`just check` runs lint, invariants, typecheck, and unit tests in that order. Run this before every commit.

## Common `just` workflows

| Goal | Recipe |
|------|--------|
| One-time workspace setup | `just setup` |
| Quality checks + Build | `just check` |
| Clean build/logs | `just clean` |
| Headless simulation | `just sim` (add `--gui` for the Gazebo GUI) |
| Connect to Serial Hardware FC | `just hw --port /dev/ttyUSB0 --baud 921600` |
| Stop everything | `just stop` (exhaustive cold teardown) |
| Run unit tests | `just test` |
| Run a live scenario | `just scenario <name>` (e.g. `just scenario 01_arm_takeoff`) |
| Run headless E2E cycle (blocks) | `just test e2e` |
| Run E2E detached (background) | `just test e2e --detach` |
| Poll a detached e2e run | `just e2e-status` |
| Tail structured logs live | `just log tail` |
| View live workspace status | `just status` |
| Validate live topic graph | `just log topics` |
| Show capability registry | `just cap show` |
| Record verified capability | `just cap record <id>` |
| Plan next claim action | `just cap plan [id]` |

Sim flags: `just sim [--gui] [--world <world>] [--model <model>] [--vision <bool>] [--overlay auto_arm|inspect|hover] [--record] [--no-build] [--timeout <s>]`. Defaults: headless, `default` world, `x500`, vision off, no overlay (boots disarmed), recording off. There is no speed flag: physics comes solely from the world SDF; any live gz `set_physics` call corrupts PX4's estimator (see `plans/065-e2e-speed-factor.md`). `just sim` always detaches and returns after readiness; watch with `just log tail`, stop with `just stop`.

## Verify (use in this order when something changed)

| Tier | Command | Needs |
|------|---------|-------|
| Fast | `just check` | Nothing running |
| Mission logic | `just mission sim <name>` | Nothing running |
| Graph | `just log topics` | `just sim` running |
| Live | `just scenario 01_arm_takeoff` | Full sim |
| All-in-one | `just test e2e` | `just setup` done, ports free |
| Record | `just cap record <id>` | Scenario PASS |
| Claims | `just cap show` / `just cap plan [id]` | Nothing running |

`/clock` missing in a hardware-style launch is expected. Use `just sim` so the Gazebo clock bridge in `sim_full.launch.py` publishes `/clock`.

## Claims

Rungs are derived, never stored: `declared < simulated < sim-flown-stale < sim-flown`. The stale rung displays as `sim-flown (stale, since <commit>)`.

| Command | Purpose |
|---------|---------|
| `just cap show` | Print every derived rung, evidence age, and stale reason. |
| `just cap plan [id]` | Print the dependency-first next-action frontier. Exit 1 while actions remain. |
| `just cap record <id>` | Record a fresh PASS after a scenario. Commit the evidence file. |

Add a claim by editing `tests/capabilities.toml`, then run `just check`. Advance it by running the action from `just cap plan`, recording the PASS, and committing `tests/evidence/<id>/`.

Nothing under `src/` reads the test registry. Full field, evidence, staleness, and exit-code contract: [docs/CLAIMS.md](docs/CLAIMS.md).

## Command verdicts and exit codes

Every command ends in a concise English verdict that states what was verified, never a bare "done". A `READY` / `PASS` line is printed only after post-conditions are confirmed, so a silently-dead stack reports `NOT READY`, never a false pass.

| Exit code | Meaning |
|-----------|---------|
| 0 | success / readiness verified / all scenarios passed |
| 1 | ran but failed (build error, NOT READY, scenario FAIL, e2e had failures) |
| 2 | usage error (unknown command/scenario, bad flag) |
| 3 | precondition failure (port busy, PX4_DIR missing/invalid, ROS not sourced) |

`just sim` boots disarmed by default; pass `--overlay auto_arm` (or trigger it from a scenario) to arm. Launch never holds the terminal: `just sim` returns after the verdict, the stack runs in the background, `just log tail` watches it, `just stop` ends it.

`just test e2e` blocks by default: it holds the terminal for the whole cycle and ends with the aggregate PASS/FAIL verdict and a fixed exit code (0 all pass, 1 any fail). Scenarios run in claims-DAG order; PASS auto-records evidence under `tests/evidence/` (skipped with a NOTE if the flight-relevant tree is dirty). Pass `--detach` to run it in a background supervisor instead: it returns after an `E2E STARTED` verdict and the cycle runs detached, watched with `just e2e-status` and stopped with `just stop`. `just e2e-status` exits 0 (finished, all pass), 1 (finished with failures, or run aborted/supervisor died), 2 (no run found), 3 (still running; output includes group progress and a `last activity Ns ago` age to tell slow from wedged). (`--wait` is a deprecated no-op alias, since blocking is now the default.)

## Reference

| Need | Where |
|------|-------|
| Stack, architecture diagram, repo layout | [README.md](README.md) |
| Frames and ENU/NED rules | [docs/FRAMES.md](docs/FRAMES.md) |
| Topic owners and types | [docs/TOPICS.md](docs/TOPICS.md) |
| MCP / rosbridge | [docs/MCP.md](docs/MCP.md). Config: `.cursor/mcp.json` |
| Mission phases and YAML schema | [docs/MISSIONS.md](docs/MISSIONS.md) |
| Claims, evidence, derived rungs | [docs/CLAIMS.md](docs/CLAIMS.md) |
| Node I/O | ROS 2 Interface block in `src/core/ros_px4_template_core/nodes/*.py` |
| Open ideas | [docs/BACKLOG.md](docs/BACKLOG.md) |

## Logs (Agent Query Workflow)

All processes (our nodes plus PX4 / Gazebo / XRCE) stream to one session log, `logs/latest.log`, in logfmt: every line is `t=<rel_s> src=<source> ...`. There are no per-node `*.jsonl` files and no `jq` step.

1. **Grep it directly**: `rg src=px4 logs/latest.log` (one source), `rg event= logs/latest.log` (state transitions), `rg ERROR logs/latest.log`, `rg -C 5 "t=42\." logs/latest.log` (everything around t=42). Field extraction needs no tool: `rg event=WAYPOINT_REACHED logs/latest.log | grep -o "err_m=[0-9.]*"`.
2. **Arc summary**: `just log summary` (re)generates and prints `logs/latest_summary.json` (run arc, errors, per-scenario pass/fail). E2E prints it automatically at the end.
3. **Live tail**: `just log tail` follows `logs/latest.log`.
4. **One scenario's verdict**: `just scenario-status [name]` prints the PASS/FAIL line for a single run from `logs/scenario_<name>.json` (default: the most recent), exit 0 pass / 1 fail / 2 missing. No `jq`.

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
| `just sim` hangs at Gazebo | `.env` has correct `PX4_DIR`; `${PX4_DIR}/build/px4_sitl_default/bin/px4` exists; on WSL confirm WSLg for GUI; `just sim` is headless by default (GUI only via `--gui`) |
| No `/fmu/out/*` topics | PX4 SITL is running and MicroXRCEAgent is on UDP 8888 (`ss -ulnp | grep 8888`); check `logs/latest.log` (`rg src=xrce`) for the XRCE handshake |
| Scenario arm fail | `gcs_heartbeat` via `uv run`; `just stop` kills MicroXRCEAgent (session key rotates each launch); `arm_delay_s` in `config/params/sim.yaml` (sim default 10s, hardware 5s) |
| Mission stuck in `takeoff` | Gate: effective ENU z (`max(pose, controller alt)`) >= `takeoff_altitude_m - takeoff_altitude_tolerance_m`. Check `position_node` output: `rg "First pose published" logs/latest.log` and confirm `/drone/odom` is publishing (`just log topics`). |
| Mission never enters `marker_hover` | Boot with `just sim --vision aruco`; check `/drone/marker_detection` publishes valid detections (`rg src=aruco_pose_publisher logs/latest.log`); the `marker_stable` guard needs `n` consecutive fresh detections (default 5) |
| `just log topics` reports missing | Topic backticked in `docs/TOPICS.md` but never published; either fix the node or remove from the manifest |
| MCP errors | See [docs/MCP.md](docs/MCP.md); confirm port 9090 open and `which uvx` path correct for the OS hosting rosbridge |
| Stale ROS daemon between runs | `just stop` (kills sim processes plus `ros2 daemon stop`) before relaunching |
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
- Missions are data-driven YAML state graphs. New behaviors/guards go in `src/core/ros_px4_template_core/lib/mission/` and are registered in `src/core/ros_px4_template_core/lib/mission/registry.py`; missions are loaded by `src/core/ros_px4_template_core/lib/mission/loader.py`. Do not embed phase logic in `src/core/ros_px4_template_core/nodes/mission_manager.py`. After adding a behavior or guard, regenerate the schema (`just mission schema > schemas/mission.schema.json`) and add its row to the `docs/MISSIONS.md` Behaviors/Guards table (both are unit-enforced).
- New scenarios go in `tests/scenarios/<NN>_<name>.py` using `spin_until` and `PX4_QOS` from `tests/scenarios/_common.py`. Scaffold a runnable stub with `just scenario-new <NN>_<name>` (writes the `Scenario` boilerplate and prints the `capabilities.toml` snippet to add), then edit the `done()` predicate. Each must end by calling `write_report`, which prints a rich one-line verdict (`PASS`/`FAIL <name> <detail> <Ns>`); pass a real `detail` (waypoint error, hold time, or the fail reason), never a bare pass. Add a claim entry in `tests/capabilities.toml` with `requires`, `scenario_file`, and `platforms = ["sim"]`; after a PASS, run `just cap record <id>` and commit the evidence file.
- Do not commit `.env`, `logs/`, `build/`, `install/`, or `log/`.

## House style

- Match the README's terse, table-heavy tone.
- No em dashes, no Unicode arrows. Use `to`, `becomes`, plain hyphens, or punctuation.
- Prefer linking back to a doc over duplicating it.


## Rules
For any file search or grep in the current git-indexed directory, use fff search mcp.
For anything relating to viewing or searching for technical information, docs, issues, or projects on GitHub, use the rich `gh` cli tool.

# Code intelligence

The repo is indexed by CodeGraph (`.codegraph/`). For structural questions
(callers, definitions, blast radius), prefer `codegraph explore "<symbols or
question>"` (shell) or the `codegraph_explore` MCP tool over grep + file
reads. Fall back to `rg` / file reads for string literals, configs, and
non-code files.
