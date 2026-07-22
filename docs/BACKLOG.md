# Backlog

Open ideas and known issues. All items below were **verified against current
code** on 2026-07-17 (done and stale-premise items moved or reworded).
Status: `idea` | `explore`.

---

## Correctness / Bugs

*(none confirmed open)*

---

## Tooling / Developer Experience

| ID | Idea | Status | Notes |
|----|------|--------|-------|
| B1 | Auto-debug or richer guidance when `check_invariants` or scenarios fail; compile a more thorough list of environment invariants that can be auto-fixed with fast, simple checks | explore | Was an inline TODO on the invariants bullet. Plans 033/034 (failure digest) covered part of the ground; the auto-fix idea stays open |
| B58a | Extend `just log topics` to enforce QoS, not just name/type/direction | idea | The type/direction half shipped (plan 006); QoS drift between nodes and docs remains unenforced. `nodes/qos.py` (plan 061) shrank the surface to one module, so this is now cheap |
| B60 | Faster-than-realtime e2e, from-boot design only: a 2x world SDF variant plus sim-time scenario timers | idea | The runtime `set_physics` path is PROVEN unsafe: any live call, even a no-op payload sent pre-arm, latently corrupts PX4's z estimate (plan 065 spike, REJECTED). Physics speed comes solely from the world SDF at boot. Salvageable pieces: plan 065's SimWindow sim-time timer design and its truth table |
| B61 | Extract the e2e detach supervisor (worker spawn, state file, status polling) from `tasks.py` into `tools/` | idea | LOW. Working and unit-covered today; worth doing only if a second supervisor (hardware e2e) appears |

---

## Perception

| ID | Idea | Status | Notes |
|----|------|--------|-------|
| B62 | Complete the real-pixel perception slice: attitude de-rotation in `aruco_pose_publisher` (tilt currently biases the body-frame offset) and a real-camera variant of scenario 08 (precision land on rendered pixels) | idea | Plan 062 proved the pipeline (0.06 m median error at 3 m, scenario 09 in e2e); these two are the known-open remainders it named |
| B63 | Obstacle and moving-target perception: today obstacles are physical but invisible to the stack (no sensor), and there is no follow-target behavior | explore | Real demand (raytheon rover-landing + obstacle_mapper challenges). Depends hard on the camera slice (B62 direction). Until then, docs/CHALLENGES.md (plan 072) documents the boundary: such rules are representable in the world, not verifiable by the stack |

---

## Strategic

| ID | Idea | Status | Notes |
|----|------|--------|-------|
| B51 | Autopilot abstraction `Protocol` in `bridges/` that wraps arm/disarm/setpoint/status; `offboard_controller` imports the protocol, not `px4_msgs` directly | idea | Unlocks PX4 version drift (1.17 to 1.18 changed topics) and ArduPilot swap. Do this before mission #5 |
| B52 | `vehicle_id` parameter + topic namespacing for multi-vehicle; today `target_system=1`, `/fmu/in/*`, `/drone/*` are all hardcoded | idea | Multi-vehicle is currently a retrofit, not a config change |
| B53 | Determinism remainder: seedable Gazebo + PX4 RNG and `just replay <run>` over recorded bags | idea | The bag/ULog/skein recording pipeline was REMOVED in plan 085 (zero consumers); resurrect from git history (plans 009-013, 048) if replay is ever picked up. Fault injection was deliberately CUT (plan 002); do not re-add it without new grounding |
| B54 | Hardware bring-up remainder: a preflight that talks to the FC over the link, and a safety-pilot interlock | idea | Premise refreshed: serial uxrce (`MicroXRCEAgent serial` in `hardware.launch.py`), `vehicles/x500.yaml` overlays, and `just hw start --port --baud --vehicle` all exist today. What is missing is a real FC preflight (link + params + sensor sanity before arming is possible) and an explicit human-interlock story |
| B55 | More mission types on the data-driven `lib/mission/` engine: behaviors/guards + YAML state graphs for non-survey missions (orbit, RTL, formation) | idea | Engine is data-driven; the gap is vocabulary. Plan 073 adds the rules-constraint guards (ceiling, time budget, keep-out box); orbit/RTL behaviors remain open |
| B56 | Config overlay expansion: `hardware.yaml` is 1 key, `common.yaml` is 5 keys; real bring-up needs 50+ (airframe, EKF, geofence, RTL, failsafe, gimbal, GPS, comms, battery, sensor cal) | idea | |
| B57 | Parameter hot-reload + mission editor/visualizer + rqt panel for `/drone/mission_status`; today changing `takeoff_altitude_m` requires edit + relaunch + 30 s PX4 boot | idea | Major drag on iteration speed |

---

## Top-3 strategic investments

If the template is going to be worth someone else's time:

1. **B62 then B63**: finish the perception slice. It is the only path from
   "markers only" to the moving-target and obstacle challenges real
   competitions pose, and plan 062 already proved the hard part.
2. **B51 + B52**: autopilot abstraction + vehicle namespacing. Unlocks
   multi-vehicle, PX4 version drift, and ArduPilot in one move. Do this
   before mission #5.
3. **B54**: hardware bring-up remainder. The launch/overlay plumbing exists;
   FC preflight and a safety-pilot interlock are what stand between sim
   verification and a real flight line.

---

## Verified done (removed from tracking)

| ID | What was fixed |
|----|----------------|
| B13 | `frame_transforms.py` velocity, yaw, and quaternion conversions (superseded again by `lib/frames.py`) |
| B20 | `mission_manager` executor/callback-group rework |
| B29 | `waypoint_mission.reached` separate XY/Z tolerances |
| B33 | `log_merger` auto-runs after every scenario run (superseded by the single logfmt session log) |
| B34 | `check-topics` `--dry-run` mode |
| B36 | Capability registry auto-updated from `scenario_<name>.json` |
| B43 | e2e scenario list driven from `tests/capabilities.toml` |
| B27 | `lib/offboard_fsm.py` pure `tick(FsmInputs)` state machine with unit tests |
| B44 | gz/PX4 boot bash extracted to `sim/launch/_start_gz_px4.sh` (plan 005) |
| B58 | `just log topics` enforces declared type and direction (plan 006); QoS sliver lives on as B58a |
| B7 | `uv` usage and the 8888/9090 port checklist are documented in README and AGENTS.md (MCP / rosbridge) |
