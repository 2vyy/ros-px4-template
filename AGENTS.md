# AGENTS.md

Operating guide for this repo. [README.md](README.md) covers the stack, architecture, and quick start; this file covers how to run, verify, and debug.

## Environment

- Gazebo, PX4 SITL, and `ros2 launch` need a Linux shell (Ubuntu 24.04 native, WSL, or distrobox). Never run builds or launches from PowerShell or cmd; on Windows, open the repo in WSL.
- Python tooling is `uv`, not pip. Tasks run through `just` (wraps `tasks.py`; `just --list` is canonical). The `justfile` auto-delegates into the `ubuntu` distrobox when host ROS is missing.
- Upstream PX4 lives outside the repo at `PX4_DIR` (set in `.env`, copied from `.env.example`).

## Invariants (do not break)

1. `src/` is sim and hardware blind. No imports from `sim/` or `hardware/` into `src/`.
2. All `src/` code uses ENU ([docs/FRAMES.md](docs/FRAMES.md)); convert only at the PX4 boundary in `nodes/offboard_controller.py` and `nodes/mission_manager.py`.
3. Never edit files inside `PX4_DIR`. Gazebo worlds and models belong in `sim/worlds` and `sim/models`.
4. `src/px4_msgs` stays on branch `release/1.17`.
5. Pure logic in `lib/` (`rclpy`-free where possible), nodes in `src/core/ros_px4_template_core/nodes/`. Mission phase logic goes in `lib/mission/`, never in `mission_manager.py`.
6. Physics speed comes solely from the world SDF. Never call gz `set_physics` live and never export `PX4_SIM_SPEED_FACTOR`; both corrupt PX4's estimator.

## Core loop

| Command | Does |
|---------|------|
| bare `just` | Live status snapshot + where to go next |
| `just check` | Format, lint, invariants, typecheck, build, unit tests. Run before every commit |
| `just sim start` | Boot headless sim detached, wait for readiness, print verdict, return |
| `just run <name>` | One scenario under the run supervisor (300s deadline, 90s log-silence watchdog) |
| `just e2e [--detach]` | Full scenario cycle in dependency order; blocks unless `--detach` |
| `just wait run --timeout <s>` | Bounded wait on the active run/cycle |
| `just runs` | Recent run records: id, verdict, reason, age |
| `just log since` | New log lines (events+errors) since your last call |
| `just stop` | Cold teardown; no process survives |

Every command is bounded and ends in an English verdict stating what was verified; only `just log tail` is unbounded. `just run` and `just e2e` are safe to launch as background tasks; alternatively `just e2e --detach` then repeated `just wait run --timeout 120` (exit 3 prints progress and means still running).

| Exit | Meaning |
|------|---------|
| 0 | success / readiness verified / all passed |
| 1 | ran but failed (build error, NOT READY, scenario FAIL) |
| 2 | usage error |
| 3 | precondition failure; for `wait`: still running at `--timeout` |

Run verdicts: `PASS` / `FAIL` (flew, missed criteria: read `just log events --run <id>`) / `STUCK` (stack or harness wedged: read `just log since`). A run record is always written to `logs/runs/`.

`just sim start` boots disarmed; pass `--overlay auto_arm` to arm. Other flags: `--gui`, `--world`, `--model`, `--vision`, `--no-build`, `--timeout`. Hardware: `just hw start --port /dev/ttyUSB0 --baud 921600`, same contract.

## Verify (in this order when something changed)

| Tier | Command | Needs |
|------|---------|-------|
| Fast | `just check` | Nothing running |
| Mission logic | `just mission sim <name>` | Nothing running |
| Graph | `just log topics` | Sim running |
| Live | `just run 01_arm_takeoff` | Full sim |
| All-in-one | `just e2e` | Ports free |
| Record | `just cap record <id>` | Scenario PASS |

## Logs

All processes (our nodes plus PX4 / Gazebo / XRCE) stream to one logfmt session log, `logs/latest.log`; every line is `t=<rel_s> src=<source> ...`. `just log since` prints only what appended since your last call (an empty result is definitive). `just log events --run <id>` slices to one run's window; `just log summary` regenerates the arc summary JSON. Or grep directly: `rg src=px4 logs/latest.log`, `rg event= logs/latest.log`, `rg -C 5 "t=42\." logs/latest.log`. Consecutive-identical lines collapse to one with `(xN)`; nothing else is filtered.

## Claims

Rungs are derived, never stored: `declared < simulated < sim-flown-stale < sim-flown`. Add a claim in `tests/capabilities.toml`, then `just check`. Advance it with the action `just cap plan` prints; after a scenario PASS, `just cap record <id>` and commit `tests/evidence/<id>/`. Full contract: [docs/CLAIMS.md](docs/CLAIMS.md).

## If X fails

| X | Check |
|---|-------|
| `just check` | `log/latest_build/`; `src/px4_msgs` on `release/1.17` |
| `just sim start` hangs at Gazebo | `PX4_DIR` in `.env` is correct and `${PX4_DIR}/build/px4_sitl_default/bin/px4` exists |
| No `/fmu/out/*` topics | MicroXRCEAgent on UDP 8888 (`ss -ulnp | grep 8888`); `rg src=xrce logs/latest.log` for the handshake |
| Scenario arm fail | `just stop` first (XRCE session key rotates each launch); `arm_delay_s` in `config/params/sim.yaml` |
| Mission stuck in `takeoff` | Confirm `/drone/odom` publishes (`just log topics`); `rg "First pose published" logs/latest.log` |
| Mission never sees markers | Boot with `--vision aruco`; `rg src=aruco_pose_publisher logs/latest.log` |
| `just log topics` reports missing | Topic backticked in `docs/TOPICS.md` but never published; fix the node or the manifest |
| Stale ROS daemon between runs | `just stop` before relaunching |
| `colcon` errors after a node move | `just clean && just check`; symlink install caches stale entry points |

## Enforced couplings when changing code

- Topic added/changed: update the node's ROS 2 Interface docstring AND its row in [docs/TOPICS.md](docs/TOPICS.md) (`just log topics` fails otherwise).
- New node: `src/core/ros_px4_template_core/nodes/` + `entry_points` in `src/core/setup.py` + a `Node(...)` line in `hardware/launch/hardware.launch.py` (both launches include it).
- New behavior/guard: register in `lib/mission/`, regenerate the schema (`just mission schema > schemas/mission.schema.json`), add its row to the [docs/MISSIONS.md](docs/MISSIONS.md) tables (all unit-enforced).
- New scenario: scaffold with `just scenario-new <NN>_<name>`, edit the `done()` predicate, add the claim entry it prints to `tests/capabilities.toml`.
- Do not commit `.env`, `logs/`, `build/`, `install/`, or `log/`.
