# Plan 044: Make battery and PX4 failsafe safe mission inputs

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving on. If a
> STOP condition occurs, stop and report. Do not improvise. When done, update
> this plan's row in `plans/README.md` unless a reviewer owns the index.
>
> **Drift check (run first)**:
> `git diff --stat e05d19b..HEAD -- src/core/ros_px4_template_core/lib/mission/types.py src/core/ros_px4_template_core/lib/mission/guards.py src/core/ros_px4_template_core/lib/mission/telemetry.py src/core/ros_px4_template_core/lib/offboard_fsm.py src/core/ros_px4_template_core/lib/events.py src/core/ros_px4_template_core/nodes/mission_manager.py src/core/ros_px4_template_core/nodes/offboard_controller.py tests/unit/test_mission_guards.py tests/unit/test_mission_telemetry.py tests/unit/test_offboard_fsm.py schemas/mission.schema.json docs/MISSIONS.md docs/TOPICS.md`
>
> Also run `git diff --stat -- <the same paths>` to expose uncommitted drift.
> Plan 041 legitimately changes both nodes first. Reconcile its target-yaw
> fields and imports without altering its contract; stop on other mismatches.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MED (safety telemetry plus automatic mode-command suppression)
- **Depends on**: none functionally; execute after plan 041 to avoid shared-file conflicts
- **Category**: direction
- **Planned at**: commit `e05d19b`, 2026-07-09

## Why this matters

The mission safety tier cannot react to battery state or record a PX4
failsafe because neither reaches its immutable `Inputs` snapshot. More
importantly, the current auto-arm FSM requests OFFBOARD whenever PX4 is in a
different mode. During a failsafe this can fight PX4's selected recovery mode.
This plan adds validated, freshness-aware telemetry and suppresses automatic
mode re-entry until an operator explicitly re-enables it.

## Current state

- `mission/types.py:10-22` has no battery or failsafe fields.
- `mission/guards.py` has pure safety predicates but no battery/failsafe guards.
- `mission_manager.py:149-189` builds a locked snapshot from odom, controller
  status, and marker data. New callbacks must use the same `_state_lock`.
- `offboard_controller.py:203-216` already receives `VehicleStatus`; its
  parameter callback clears the disarm latch on explicit `auto_arm=true`.
- `offboard_fsm.py:70-72` requests OFFBOARD every two seconds whenever
  effective auto-arm is true and `nav_state != OFFBOARD`.
- `BatteryStatus.msg` is version 1. `remaining` uses `-1` as invalid and the
  message exposes `connected`; treating raw `-1` as low battery is unsafe.
- `VehicleStatus.msg` is version 1 and exposes `failsafe: bool`.
- Existing PX4 QoS is BEST_EFFORT, TRANSIENT_LOCAL, KEEP_LAST depth 10.

## Design decisions

### Unknown and stale battery is not low battery

`Inputs.battery_remaining` is `float | None`, default `None`. A value is
usable only when the battery is connected, finite, in `[0, 1]`, and fresh.
The `battery_low` guard returns false for unknown/stale data. Missions that
need fail-closed telemetry can separately use `inputs_stale` with key
`battery`.

### PX4 remains the failsafe authority

`failsafe_active` lets the mission record or change its logical state, but it
does not override PX4's selected action. On the first active failsafe,
`offboard_controller` latches automatic arm/mode commands off. The latch is
cleared only by an explicit `auto_arm=true` parameter set after PX4 reports
that failsafe is inactive. Existing OffboardControlMode/setpoint streaming is
not stopped while PX4 remains in OFFBOARD; only new arm or mode commands are
suppressed.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Pure tests | `uv run pytest tests/unit/test_mission_guards.py tests/unit/test_mission_telemetry.py tests/unit/test_offboard_fsm.py -q` | all pass |
| Schema | `just mission schema` | output contains both new guards |
| Full gate | `just check` | exit 0 |
| Topic check | `just sim` then `ros2 topic list` | battery topic name confirmed |
| Live battery guard | see Step 7 | structured `battery_low` transition |

## Scope

**In scope**:

- `src/core/ros_px4_template_core/lib/mission/types.py`
- `src/core/ros_px4_template_core/lib/mission/guards.py`
- `src/core/ros_px4_template_core/lib/mission/telemetry.py` (create)
- `src/core/ros_px4_template_core/lib/offboard_fsm.py`
- `src/core/ros_px4_template_core/lib/events.py`
- `src/core/ros_px4_template_core/nodes/mission_manager.py`
- `src/core/ros_px4_template_core/nodes/offboard_controller.py`
- `tests/unit/test_mission_guards.py`
- `tests/unit/test_mission_telemetry.py` (create)
- `tests/unit/test_offboard_fsm.py`
- `schemas/mission.schema.json`
- `docs/MISSIONS.md`, `docs/TOPICS.md`
- `plans/README.md` status only

**Out of scope**:

- Changing shipped missions to opt into the guards.
- Battery filtering, capacity estimation, multi-battery arbitration, or PX4
  failsafe parameter tuning.
- Mapping `estimate_ok`; no correct estimator-health field is established.
- Stopping PX4 offboard streams solely because `failsafe` is true.
- Editing PX4 message definitions or files under `PX4_DIR`.

## Git workflow

- Branch: `advisor/044-battery-failsafe`
- Commit: `feat(safety): expose battery and latch offboard on failsafe`
- Do not push or open a PR without operator instruction.

## Steps

### Step 1: Normalize battery telemetry in pure code

Create `mission/telemetry.py` with no ROS imports. Add:

```python
def usable_battery_remaining(*, connected: bool, remaining: float) -> float | None:
    ...
```

Return `None` when disconnected, non-finite, or outside `[0, 1]`; otherwise
return the float. Tests must cover `-1`, NaN, infinity, disconnected values,
zero, one, and a normal fraction.

**Verify**: `uv run pytest tests/unit/test_mission_telemetry.py -q` -> all pass.

### Step 2: Extend immutable inputs and guards

Append defaulted fields to `Inputs`:

```python
battery_remaining: float | None = None
failsafe_active: bool = False
```

Add guards:

- `battery_low`: true only when `battery_remaining` is not `None`, battery
  age is at most `max_age_s` (default 5.0), and remaining is at or below
  `frac` (default 0.2).
- `failsafe_active`: mirrors the snapshot boolean.

Reject a configured `frac` outside `[0, 1]` with a clear `ValueError`; add
tests so malformed mission parameters cannot silently invert safety logic.
Extend the test `_inputs` helper with optional battery and failsafe kwargs.

Tests must cover threshold boundaries, custom threshold, unknown battery,
stale battery, default fields, active/inactive failsafe, and invalid `frac`.

**Verify**: `uv run pytest tests/unit/test_mission_guards.py -q` -> all pass.

### Step 3: Subscribe and snapshot under the existing lock

In `mission_manager`:

1. Add the PX4 QoS profile matching `offboard_controller`.
2. Import `BatteryStatus` and `VehicleStatus`.
3. Initialize battery to `None`, battery timestamp to `0.0`, failsafe to
   false, and vehicle-status timestamp to `0.0`.
4. Subscribe to `/fmu/out/battery_status_v1` and
   `/fmu/out/vehicle_status_v1` with `_PX4_QOS` and `_sub_group`.
5. In each callback, compute values before taking `_state_lock`, then update
   value and timestamp together while holding the lock.
6. Copy both values and timestamps inside the existing `_snapshot` lock.
7. Add `battery` and `vehicle_status` ages to `input_ages`; pass the new
   fields to `Inputs`.
8. Leave `_estimate_ok` unchanged.
9. Update the node's ROS 2 Interface docstring.

**Verify**: `uv run ruff check src/core/ros_px4_template_core/nodes/mission_manager.py`
-> exit 0.

### Step 4: Add a failsafe latch to automatic mode commands

Add a pure helper to `offboard_fsm.py`:

```python
def auto_arm_allowed(requested: bool, *, disarm_latched: bool, failsafe_latched: bool) -> bool:
    return requested and not disarm_latched and not failsafe_latched
```

Cover its truth table in `test_offboard_fsm.py`.

In `offboard_controller`:

1. Track `_failsafe_active` and `_failsafe_latched`.
2. In `_status_cb`, latch on the rising edge of `msg.failsafe` and log
   `FAILSAFE_MODE_COMMANDS_LATCHED`. Log when the live failsafe clears, but
   do not clear the latch automatically.
3. Compute effective `_auto_arm` with `auto_arm_allowed`.
4. On explicit `auto_arm=true`, reject the parameter update while live
   failsafe is active. Otherwise clear both disarm and failsafe latches and
   log which latch was cleared.
5. Do not change `_control_loop` streaming conditions. PX4 still owns the
   live mode transition.
6. Add canonical event names to `lib/events.py`.

**Verify**: `uv run pytest tests/unit/test_offboard_fsm.py -q` and
`uv run ruff check src/core/ros_px4_template_core/nodes/offboard_controller.py`
-> both pass.

### Step 5: Regenerate schema and update docs

Regenerate `schemas/mission.schema.json` and confirm only the two new guard
names are added.

Update `docs/TOPICS.md` for the battery publication and both mission-manager
subscriptions. Update `docs/MISSIONS.md` with:

- `battery_low` params `frac` and `max_age_s`;
- `failsafe_active` semantics;
- an example battery diversion to `return_to_origin`;
- a warning that a failsafe transition is logical observability only, PX4
  owns the action, and the controller will not re-request OFFBOARD until an
  explicit safe re-enable.

Do not show `failsafe_active -> hold_safe` as if mission hold overrides PX4.

**Verify**: `uv run pytest tests/unit/test_mission_schema.py -q` -> pass;
`uv run python tools/check_docs.py` -> pass.

### Step 6: Run the full gate

**Verify**: `just check` -> exit 0.

### Step 7: Perform live topic and guard verification

1. `just sim` -> READY.
2. Confirm `/fmu/out/battery_status_v1` exists and echo one message. Record
   `connected` and `remaining` without assuming SITL starts below 1.0.
3. Run `just log topics` after the manifest update -> PASS.
4. Use a temporary mission/overlay with a battery threshold just above the
   observed valid fraction. Relaunch it and confirm a structured
   `TRANSITION` with `guard=battery_low`.
5. Run `just scenario 01_arm_takeoff` -> PASS.
6. Do not force a real PX4 failsafe merely to test the latch. The pure helper
   and node review cover that path; future fault-injection work may add a
   safe live scenario.

If the battery topic is absent, stop before marking DONE. Do not remove the
manifest row to make the topic check pass.

## Test plan

- Pure normalization tests for every invalid `BatteryStatus.remaining` form.
- Guard truth tables including unknown and stale data.
- Pure auto-arm suppression truth table.
- Schema drift test.
- Live battery-topic name, valid sample, forced threshold transition, topic
  audit, and existing flight regression.

## Done criteria

- [ ] Invalid/disconnected battery never triggers `battery_low`.
- [ ] Stale battery does not trigger `battery_low`; `inputs_stale` can detect it.
- [ ] All new mission-manager state is copied under `_state_lock`.
- [ ] Active or latched failsafe makes effective auto-arm false.
- [ ] Failsafe latch cannot be cleared while live failsafe remains active.
- [ ] `just check` exits 0.
- [ ] Battery topic exists live and `just log topics` passes.
- [ ] Forced battery transition and scenario 01 regression are recorded.
- [ ] Only in-scope files changed; the plan index row is updated.

## STOP conditions

- The live topic is absent or has a different message contract.
- `BatteryStatus.remaining` invalid semantics differ from the committed
  `release/1.17` message definition.
- Implementing the latch requires stopping offboard streams while PX4 still
  reports OFFBOARD. Report the mode behavior instead of guessing.
- PX4 resumes OFFBOARD automatically during an observed failsafe despite
  effective auto-arm being false.
- Plan 041's optional-yaw contract would need to be changed.

## Maintenance notes

- A future multi-battery plan should select a primary battery before filling
  this single optional fraction.
- Hardware operators can combine `battery_low` with `inputs_stale` when the
  competition policy requires fail-closed telemetry.
- Plan 042 must preserve both disarm and failsafe latches when adding landing
  handoff state.
