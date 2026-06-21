# Backlog

Open ideas and known issues. All items below are **verified against current code** (done items removed).
Status: `idea` | `explore`.

---

## Correctness / Bugs

*(none confirmed open — B13 and B20 are fixed)*

---

## Tooling / Developer Experience

| ID | Idea | Status | Notes |
|----|------|--------|-------|
| B1 | Auto-debug or richer guidance when `check_invariants` or scenarios fail; compile a more thorough list of environment invariants that can be auto-fixed with fast, simple checks | explore | Was an inline TODO on the invariants bullet |
| B7 | Document `uv` at repo root (`pyproject.toml` dev deps) and consolidate a port checklist (MicroXRCE 8888, rosbridge 9090) in a user-facing location | idea | Currently only documented in CLAUDE.md |
| B44 | Extract `gz_px4_stack` ~100-line bash blob from `sim_full.launch.py` to `sim/launch/_start_gz_px4.sh` | idea | LOW |
| B58 | Extend `check-topics` to enforce types / QoS / direction, not just names — ROS docstrings in nodes duplicate `docs/TOPICS.md` by hand and drift is guaranteed | idea | MEDIUM. Particularly painful with >1 contributor |

---

## Strategic

| ID | Idea | Status | Notes |
|----|------|--------|-------|
| B51 | Autopilot abstraction `Protocol` in `bridges/` — wraps arm/disarm/setpoint/status; `offboard_controller` imports the protocol, not `px4_msgs` directly | idea | Unlocks PX4 version drift (1.17→1.18 changed topics) and ArduPilot swap. Pay before mission #5 |
| B52 | `vehicle_id` parameter + topic namespacing for multi-vehicle — today `target_system=1`, `/fmu/in/*`, `/drone/*` are all hardcoded | idea | Multi-vehicle is currently a retrofit, not a config change |
| B53 | Determinism stack: auto-rosbag every sim run → `logs/run_<ts>.bag`; `just replay <bag>`; seedable Gazebo + PX4 RNG; fault scenarios (GPS dropout / wind / motor failure) wired into the e2e harness | idea | Biggest missing affordance for "rapid ROS dev" — turns one-shot scenarios into deterministic regression assets |
| B54 | Real hardware bring-up: actual uxrce serial in `hardware.launch.py` (today declares `serial_port`/`baudrate` but never uses them); preflight that talks to the FC; safety-pilot interlock; `vehicles/<name>.yaml` overlay | idea | Template name overpromises until this lands |
| B55 | More mission types on the data-driven `lib/mission/` engine: behaviors/guards + YAML state graphs for non-survey missions (orbit, RTL, search-pattern, formation) | idea | Engine already data-driven; gap is the behavior/guard + mission-YAML library |
| B56 | Config overlay expansion — `hardware.yaml` is 1 key, `common.yaml` is 5 keys; real bring-up needs 50+: airframe, EKF, geofence, RTL, failsafe, gimbal, GPS, comms, battery, sensor cal | idea | |
| B57 | Parameter hot-reload + mission editor/visualizer + rqt panel for `/drone/mission_status` — today changing `takeoff_altitude_m` requires edit + relaunch + 30 s PX4 boot | idea | Major drag on iteration speed |

---

## Top-3 strategic investments

If the template is going to be worth someone else's time:

1. **B51 + B52** — autopilot abstraction + vehicle namespacing. Unlocks multi-vehicle, PX4 version drift, and ArduPilot in one move. Pay this cost before mission #5.
2. **B54** — real hardware bring-up. `hardware.launch.py` is currently a stub. The "template" name overpromises until uxrce serial works, preflight talks to the FC, and a second airframe is a config overlay.
3. **B53** — determinism + replay + fault injection. Auto-rosbag every run, `just replay`, seedable physics, and fault scenarios in the e2e harness. Turns "I can demo arm+takeoff" into "I can iterate on edge-case mission logic in minutes" — the actual promise of rapid ROS dev.

---

## Verified done (removed from tracking)

| ID | What was fixed |
|----|----------------|
| B13 | `frame_transforms.py` now has velocity, yaw, and quaternion conversions — not position-only |
| B20 | `mission_manager` now uses `MultiThreadedExecutor` + `MutuallyExclusiveCallbackGroup` / `ReentrantCallbackGroup` |
| B29 | `waypoint_mission.reached` now has separate XY/Z tolerances |
| B33 | `log_merger` now auto-runs after every `just scenario` |
| B34 | `check-topics` has `--dry-run` mode (grep sources, no live sim) |
| B36 | Capability registry auto-updated from `scenario_<name>.json` after each `just scenario` |
| B43 | `e2e` scenario list driven from `tests/capabilities.toml` (sim platform filter) |
| B27 | `lib/offboard_fsm.py` is a pure `tick(FsmInputs)` state machine, imported by `offboard_controller`; `tests/unit/test_offboard_fsm.py` covers it |
