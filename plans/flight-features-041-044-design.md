# Flight Features 041-044 Design

**Approved:** 2026-07-09

**Baseline:** `e05d19b`

**Scope:** Plans 041 through 044 only

## Goal

Finish the remaining flight-feature roadmap as four independently reviewable
changes with one shared safety contract. Yaw control establishes the target
transport contract, battery and failsafe handling establishes automatic-mode
inhibition, precision landing reuses that inhibition, and competition worlds
remain an additive simulation-assets track.

## Execution order

1. Plan 041: optional mission yaw end to end.
2. Plan 044: validated battery/failsafe inputs and generic automatic-mode
   inhibition.
3. Plan 042: precision landing and NAV_LAND handoff, reusing the inhibit.
4. Plan 043: competition worlds and marker assets. This plan is functionally
   independent and may run earlier, but it must not run concurrently with a
   plan that changes the same package-data or documentation files.

Plans 041, 044, and 042 run sequentially because they share
`mission_manager.py` and `offboard_controller.py`. Plan 043 does not gate the
synthetic-camera landing scenario.

## Shared control-authority contract

The configured `auto_arm` parameter expresses operator intent. Runtime safety
conditions may inhibit that intent without overwriting the parameter. The
offboard state machine receives an explicit, generic automatic-mode inhibition
input and emits neither OFFBOARD nor arm requests while inhibited.

The controller records independent inhibit reasons. Plan 044 introduces PX4
failsafe inhibition; plan 042 adds landing inhibition. An explicit
`auto_arm=true` parameter update may clear a latched reason only after its live
condition has cleared. It must not override an active PX4 failsafe or an active
landing handoff. Disarm latching from plan 030 remains in force.

## Plan 041: optional yaw transport

Mission YAML expresses yaw as `yaw_deg` in ENU: zero is East and positive is
counter-clockwise. `GoTo.yaw` carries ENU radians. ENU-to-NED conversion occurs
only in `offboard_controller` when publishing PX4 `TrajectorySetpoint.yaw`.

`/drone/target_pose` uses this internal orientation contract:

- An all-zero quaternion means yaw is omitted, so PX4 yaw remains NaN.
- A finite near-unit quaternion carries commanded ENU yaw.
- A non-zero malformed quaternion is treated as omitted and produces a
  rate-limited diagnostic without raising from a ROS callback.

The codec is pure Python and owns sentinel detection, norm validation,
normalization, and yaw extraction. Waypoint entries contain exactly
`[x, y, z]` or `[x, y, z, yaw_deg]`; any other length is rejected with an error
that identifies the entry.

Acceptance uses `07_yaw_control.py`. It proves YAML-to-PX4 yaw conversion and
actual vehicle heading, while an existing position-only scenario proves that
omitted yaw still produces NaN.

## Plan 044: battery and PX4 failsafe inputs

Battery telemetry is unknown until a sample is connected, finite, in the
inclusive range `[0.0, 1.0]`, and fresh. `BatteryStatus.remaining == -1`, a
disconnected battery, a non-finite value, an out-of-range value, or a stale
sample yields unknown battery state. `battery_low` is false for unknown state;
PX4 remains responsible for its native battery failsafes.

Mission-manager callbacks update battery and failsafe state under the existing
state lock. Each mission tick snapshots immutable values and ages. The plan
does not assign estimator health from unrelated `VehicleStatus` fields.

An active PX4 failsafe immediately inhibits automatic OFFBOARD and arm
requests. The inhibit remains latched after the live failsafe clears until an
operator explicitly updates `auto_arm=true`. Such an update cannot clear the
inhibit while `VehicleStatus.failsafe` is still true. Unit coverage exercises
the pure state machine, invalid battery values, freshness expiry, latch
clearing, and the absence of mode commands during inhibition.

## Plan 042: precision landing and reacquisition

The mission graph is explicit:

```text
takeoff -> approach -> reacquire -> descend -> done
                        ^    |         |
                        |    +---------+
                        |   marker lost
                        +-- stable marker resumes descent
```

`approach` may enter `descend` only through a stable observation of the
selected marker. Reaching the approach waypoint without a stable marker enters
`reacquire`; there is no `waypoints_done -> descend` transition.

`center_land` descends only while the selected detection is fresh and the
vehicle is centered. If the detection becomes stale or disappears, the
behavior retains the last XY target, freezes commanded altitude before the FSM
evaluates transitions, and emits a signal that sends the mission to
`reacquire`. The mission YAML documents this contract beside the states and
transitions. `reacquire` holds the current pose and returns to `descend` only
after the selected marker is stable again.

The mission engine clears state scratch on every transition. Re-entering
`descend` therefore initializes its descent command from current vehicle
altitude rather than the altitude from the previous descent episode. Negative
or anomalously large time deltas cannot increase descent distance; elapsed time
is clamped to a documented non-negative maximum per tick.

`Land` is emitted once per landing episode. Mission-manager state resets when a
non-Land command resumes so a later episode may issue a new handoff.
`offboard_controller` inhibits automatic mode requests before sending
`VEHICLE_CMD_NAV_LAND`. NAV_LAND acknowledgements are logged. A rejected or
failed acknowledgement remains inhibited, is not blindly retried, and causes
the live scenario to fail.

Acceptance uses `08_precision_land.py`. It must prove stable-marker entry,
descent, altitude freeze after synthetic marker loss, reacquisition, resumed
descent, NAV_LAND acceptance, disarm, terminal mission state, and no later arm
or OFFBOARD command.

## Plan 043: deterministic competition assets

World and model assets stay under `sim/worlds` and `sim/models`; no PX4 tree is
modified. The default world remains unchanged. New worlds retain the default
world's flight-verified physics, magnetic field, light, and spherical
coordinate blocks, and each SDF world name equals its filename stem.

Marker maps are world-specific package resources rather than additions to the
global default map. Overlays select the map appropriate to the selected
practice world. The generator is deterministic and tests generated dimensions
and content.

The detector's `marker_size_m = 0.2` refers to the black ArUco code. A 512 px
black code centered in a 615 px texture therefore uses an SDF physical side
length of `0.2 * 615 / 512 = 0.240234375 m`. The surrounding quiet border does
not shrink the black code below the configured detector size.

These assets support GUI inspection, course rehearsal, and a future
camera-equipped vehicle. They do not claim real-camera end-to-end coverage for
the current x500 model. Existing synthetic-camera scenarios remain the
automated perception and precision-landing gates.

## Error handling and STOP conditions

- Stop if a yaw-free mission produces finite PX4 yaw or ENU/NED conversion is
  required outside the PX4 boundary.
- Stop if invalid battery telemetry can trigger `battery_low`, or if an active
  PX4 failsafe permits an OFFBOARD or arm request.
- Stop a landing run if the vehicle descends with a stale marker, enters
  NAV_LAND without a stable-marker descent episode, or re-enters OFFBOARD after
  handoff.
- Stop if PX4 rejects NAV_LAND. Preserve inhibition and report the
  acknowledgement; do not add an unbounded retry loop.
- Stop if marker texture geometry makes the rendered black code differ from
  the configured physical marker size.
- Never mark a live capability DONE when its simulator scenario has not passed.

## Verification strategy

Each plan follows test-driven steps and ends with `just check`. Registry
changes regenerate and verify `schemas/mission.schema.json`; new topics update
both node interface docstrings and `docs/TOPICS.md`; new mission behavior and
guard contracts update `docs/MISSIONS.md`.

Plan-specific unit tests cover pure codecs, frame conversion, behavior timing,
marker freshness, telemetry validity, guards, control inhibition, and asset
generation. Live scenarios use the capability registry and record capability
status only after PASS. The final integrated regression is `just test e2e`.

## Explicitly deferred

- Yaw-rate commands and automatic tangent yaw.
- Moving-platform landing and velocity feed-forward.
- PX4 landing-parameter tuning.
- A camera-equipped Gazebo vehicle model and real rendered-image E2E tests.
- A mission-level response to unknown battery telemetry beyond PX4's native
  failsafes.
