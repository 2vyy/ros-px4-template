# AGENTS.md

Operating guide for an agent driving this repo. [README.md](README.md) is the overview (stack, architecture, quick start); this file is the operational contract: invariants, command surface, verification tiers, logs, and failure modes. Initial setup: complete the [README quick start](README.md#quick-start) once.

## Where to run

| Context | Rule |
|---------|------|
| Ubuntu 24.04 native | `just <recipe>` in a project shell with Jazzy on PATH |
| WSL | Open repo in WSL, run `just <recipe>` in a WSL shell |
| WSL fallback (repo on `C:\`, agent in PowerShell) | `wsl -d Ubuntu -- bash -lc 'cd ~/Projects/ros-px4-template && just <recipe>'` |
| Distrobox | `distrobox enter ubuntu -- bash -lc 'cd ~/Projects/ros-px4-template && just <recipe>'` |

Never run `just build`, `just sim start`, or `colcon` from PowerShell or cmd; Gazebo, PX4 SITL, and `ros2 launch` need a Linux shell. Unsure of context: `uname -a` first. The `justfile` auto-delegates to the distrobox when host ROS is missing.

## Invariants (do not break)

1. `src/` is sim and hardware blind. No imports from `sim/` or `hardware/` into `src/`.
2. All `src/` code uses ENU ([docs/FRAMES.md](docs/FRAMES.md)); convert only at the PX4 boundary in `src/core/ros_px4_template_core/nodes/offboard_controller.py` and `nodes/mission_manager.py`.
3. Never edit files inside `PX4_DIR`. Gazebo worlds and models belong in `sim/worlds` and `sim/models`.
4. `src/px4_msgs` stays on branch `release/1.17`. Enforced by `tools/check_invariants.py`.
5. Pure logic in `lib/` (`rclpy`-free where possible), nodes in `src/core/ros_px4_template_core/nodes/`.
6. `sim/launch/sim_full.launch.py` is the full sim. `hardware/launch/hardware.launch.py` is rosbridge plus core nodes only, included by the sim launch with `config:=sim`.
7. Physics speed comes solely from the world SDF. Never call gz `set_physics` live and never export `PX4_SIM_SPEED_FACTOR`; both latently corrupt PX4's estimator (plan 065).

## Command surface

`just --list` is canonical. Every recipe wraps `tasks.py` through a sourced-environment shim.

| Recipe | Does | Bounds |
|--------|------|--------|
| bare `just` | Live status snapshot (stack state, nodes, recent verdicts) + where to go next | instant |
| `just setup` | One-time workspace setup: px4_msgs clone, uv sync, rosdep, build | network-bound |
| `just check` | Quality gate: format, lint-fix, invariants, typecheck, colcon build, unit tests, docs check. Run before every commit | minutes |
| `just test` | Smart-build + pytest unit suite only | minutes |
| `just clean` | Wipe build artifacts, build logs, per-run logs | instant |
| `just sim start [flags]` | Smart-build, boot detached, wait for readiness, print verdict, return. Never holds the terminal | `--timeout` |
| `just hw start [flags]` | Same detached + verdict contract for a serial FC (`--port /dev/ttyUSB0 --baud 921600`) | `--timeout` |
| `just stop` | Exhaustive cold teardown (includes `ros2 daemon stop`, MicroXRCEAgent); no process survives | bounded |
| `just run <name>` | One scenario under the run supervisor; always leaves a run record | 300s deadline + 90s silence watchdog |
| `just e2e [--detach]` | Full cycle in claims-DAG order; blocks by default, `--detach` backgrounds it | per-run supervisor bounds |
| `just wait ready` | Bounded wait for stack readiness | `--timeout`, exit 3 if not ready |
| `just wait run` | Bounded wait on the active run/cycle; prints verdict or progress | `--timeout`, exit 3 still running |
| `just runs` | Recent run records: id, verdict, reason, age | instant |
| `just log <sub>` | `since` (delta read), `events` (transitions, `--run <id>` slices), `summary`, `tail` (unbounded, human-only), `topics` (live graph audit) | instant except `tail` |
| `just mission <sub>` | `list`, `validate <name>`, `show <name>`, `sim <name>`, `schema`; <1s, no ROS, no sim | instant |
| `just cap <sub>` | `show` (derived rungs), `plan` (next-action frontier), `record <id>` (commit PASS evidence) | instant |
| `just scenario-new <NN>_<name>` | Scaffold a runnable scenario stub + `capabilities.toml` snippet | instant |
| `just analyze [id]` | Overlay + query a `--record` run via skein (sibling repo) | bounded |

Sim flags: `just sim start [--gui] [--world <world>] [--model <model>] [--vision <bool|aruco>] [--overlay auto_arm|inspect|hover] [--record] [--no-build] [--timeout <s>]`. Defaults: headless, `default` world, `x500`, vision off, no overlay (boots disarmed), recording off. Watch with `just log tail`, stop with `just stop`.

### Verdicts and exit codes

Every command ends in a concise English verdict stating what was verified, never a bare "done". `READY`/`PASS` prints only after post-conditions are confirmed: a silently dead stack reports `NOT READY`, never a false pass.

| Exit | Meaning |
|------|---------|
| 0 | success / readiness verified / all scenarios passed |
| 1 | ran but failed (build error, NOT READY, scenario FAIL, e2e had failures) |
| 2 | usage error (unknown command/scenario, bad flag) |
| 3 | precondition failure (port busy, `PX4_DIR` missing, ROS not sourced) or, for `wait`, still running at `--timeout` |

Run verdicts: `PASS` / `FAIL` (flew, missed criteria; read the mission events) / `STUCK` (stack or harness wedged; read the stack log). `just wait run` exits 0 (finished, all pass), 1 (failures, or run aborted / supervisor died), 2 (nothing to wait on), 3 (still running; output includes the heartbeat snapshot to tell slow from wedged).

### Harness contract (bounded commands)

Every command is bounded: launches wait-with-timeout, runs execute under a supervisor (hard 300s deadline + 90s log-silence watchdog, verdict file always written to `logs/runs/`), waits take `--timeout` and exit 3 with a progress snapshot. The only intentionally unbounded command is `just log tail` (human-only).

| Driving agent | Long-running workflow |
|---------------|----------------------|
| Claude Code | Launch `just run <name>` or `just e2e` as a background task; the harness re-invokes you when the verdict lands. No polling. |
| Any harness | `just e2e --detach`, then repeated `just wait run --timeout 120`; each timeout prints progress and exits 3. |

`just e2e` details: scenarios run in claims-DAG order; a failed claim's dependents are skipped as `prerequisite_failed`; each PASS auto-records evidence under `tests/evidence/` (skipped with a NOTE if the flight-relevant tree is dirty). Aggregate exit: 0 all pass, 1 any fail. (`--wait` is a deprecated no-op alias; blocking is the default.)

`just sim start` boots disarmed; pass `--overlay auto_arm` (or let the scenario trigger it) to arm.

## Verify (in this order when something changed)

| Tier | Command | Needs |
|------|---------|-------|
| Fast | `just check` | Nothing running |
| Mission logic | `just mission sim <name>` | Nothing running |
| Graph | `just log topics` | `just sim start` running |
| Live | `just run 01_arm_takeoff` | Full sim |
| All-in-one | `just e2e` | `just setup` done, ports free |
| Record | `just cap record <id>` | Scenario PASS |
| Claims | `just cap show` / `just cap plan [id]` | Nothing running |

`/clock` missing in a hardware-style launch is expected; only `sim_full.launch.py` bridges the Gazebo clock.

## Logs (agent query workflow)

All processes (our nodes plus PX4 / Gazebo / XRCE) stream to one session log, `logs/latest.log`, in logfmt: every line is `t=<rel_s> src=<source> ...`. No per-node files, no `jq`.

1. **Incremental read**: `just log since` prints only what appended since your last call (events+errors by default, `--raw` for everything) with an aggregate trailer. An empty result is definitive. `just log events --run <id>` slices to one run record's window.
2. **Grep directly**: `rg src=px4 logs/latest.log` (one source), `rg event= logs/latest.log` (state transitions), `rg ERROR logs/latest.log`, `rg -C 5 "t=42\." logs/latest.log` (context around t=42). Field extraction: `rg event=WAYPOINT_REACHED logs/latest.log | grep -o "err_m=[0-9.]*"`.
3. **Arc summary**: `just log summary` (re)generates `logs/latest_summary.json` (run arc, errors, per-scenario pass/fail). E2E prints it automatically.
4. **Live tail**: `just log tail` (human-only, unbounded).
5. **Run verdicts**: `just runs` lists recent records; `just wait run` blocks (bounded) on the active run.

Consecutive-identical lines collapse to one with a trailing `(xN)`; nothing else is filtered, so a smoking gun is never hidden.

## Claims

Rungs are derived, never stored: `declared < simulated < sim-flown-stale < sim-flown` (stale displays as `sim-flown (stale, since <commit>)`). Add a claim by editing `tests/capabilities.toml`, then `just check`. Advance it: run the action `just cap plan` prints, `just cap record <id>` after the PASS, commit `tests/evidence/<id>/`. Nothing under `src/` reads the registry. Full contract: [docs/CLAIMS.md](docs/CLAIMS.md).

## MCP / rosbridge

- rosbridge WebSocket on port 9090, started by `hardware.launch.py` (included by `sim_full.launch.py`), so both `just sim start` and `just hw start` bring it up. Requires `ros-jazzy-rosbridge-suite` in the ROS environment.
- MicroXRCEAgent on UDP 8888, started by `sim_full.launch.py`.
- Check the port with `nc -z 127.0.0.1 9090` or `ss -tlnp | grep 9090` (do not point HTTP curl at the WebSocket).
- MCP client config lives in `.cursor/mcp.json`: `command` must be the literal output of `which uvx` on the same OS that runs rosbridge (no `${userHome}`), args `["ros-mcp", "--transport=stdio"]`.
- Cross-OS gotcha: a Windows IDE pointing at WSL rosbridge does not work; the MCP client and rosbridge need one OS view of filesystem and network. Run both in WSL.
- Typical session: `just sim start`, wait for the READY verdict (it confirms `/fmu/out/*` and rosbridge), connect MCP to `127.0.0.1:9090`.

## If X fails

| X | Check |
|---|-------|
| `just check` | `log/latest_build/`; `src/px4_msgs` on `release/1.17`; ROS sourced or distrobox available (justfile handles this) |
| `just sim start` hangs at Gazebo | `.env` has correct `PX4_DIR`; `${PX4_DIR}/build/px4_sitl_default/bin/px4` exists; on WSL confirm WSLg for `--gui` |
| No `/fmu/out/*` topics | PX4 SITL running and MicroXRCEAgent on UDP 8888 (`ss -ulnp | grep 8888`); `rg src=xrce logs/latest.log` for the handshake |
| Scenario arm fail | `just stop` first (XRCE session key rotates each launch); `arm_delay_s` in `config/params/sim.yaml` (sim 10s, hardware 5s) |
| Mission stuck in `takeoff` | Gate: effective ENU z (`max(pose, controller alt)`) >= `takeoff_altitude_m - takeoff_altitude_tolerance_m`. `rg "First pose published" logs/latest.log`; confirm `/drone/odom` publishes (`just log topics`) |
| Mission never enters `marker_hover` | Boot with `--vision aruco`; `rg src=aruco_pose_publisher logs/latest.log`; `marker_stable` needs `n` consecutive fresh detections (default 5) |
| Run verdict STUCK | `just log since` for the last lines before silence; heartbeat snapshot in the verdict names the wedged phase |
| `just log topics` reports missing | Topic backticked in `docs/TOPICS.md` but never published; fix the node or the manifest |
| MCP errors | Port 9090 open; `which uvx` path correct for the OS hosting rosbridge (section above) |
| Stale ROS daemon between runs | `just stop` before relaunching |
| `colcon` errors after a node move | `just clean && just check`; symlink install caches stale entry points |

## Code changes

- **Topic added/changed**: update the node's ROS 2 Interface docstring AND the row in [docs/TOPICS.md](docs/TOPICS.md); `just log topics` fails otherwise once the sim is up.
- **New node**: create under `src/core/ros_px4_template_core/nodes/`; add to `entry_points["console_scripts"]` in `src/core/setup.py`; add a `Node(...)` line in `hardware/launch/hardware.launch.py` (both launches pick it up); `just check` then verify with bare `just` or `ros2 node list`.
- **New library**: `src/core/ros_px4_template_core/lib/` + unit tests in `tests/unit/`. Keep `lib/` `rclpy`-free where possible (see the `StructuredLogger` Protocol pattern). Use `StructuredLogger` for agent-facing diagnostics; call `self.slog.close()` from `destroy_node`.
- **New behavior/guard**: pure function in `lib/mission/behaviors.py` / `guards.py`, registered by decorator; unit test; regenerate the schema (`just mission schema > schemas/mission.schema.json`) and add its row to the [docs/MISSIONS.md](docs/MISSIONS.md) tables (both unit-enforced). Do not embed phase logic in `mission_manager.py`.
- **New scenario**: `just scenario-new <NN>_<name>` scaffolds the stub and prints the `capabilities.toml` snippet; edit the `done()` predicate; end with `write_report` carrying a real `detail` (waypoint error, hold time, fail reason), never a bare pass. Then `just run <NN>_<name>`, `just cap record <id>`, commit the evidence.
- Do not commit `.env`, `logs/`, `build/`, `install/`, or `log/`.

## House style

- Terse, table-heavy. No em dashes, no Unicode arrows: use `to`, `becomes`, plain hyphens, or punctuation.
- Prefer linking to a doc over duplicating it.

## Rules

For any file search or grep in the current git-indexed directory, use fff search mcp.
For anything relating to viewing or searching for technical information, docs, issues, or projects on GitHub, use the rich `gh` cli tool.

## Code intelligence

The repo is indexed by CodeGraph (`.codegraph/`). For structural questions (callers, definitions, blast radius), prefer `codegraph explore "<symbols or question>"` (shell) or the `codegraph_explore` MCP tool over grep + file reads. Fall back to `rg` / file reads for string literals, configs, and non-code files.
