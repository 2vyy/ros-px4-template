# Plan 042: Precision landing on a marker (`center_land` behavior, `Land` executed end to end)

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report - do not improvise. When done, update the status row for this plan
> in `plans/README.md` - unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat ead4cc6..HEAD -- src/core/ros_px4_template_core/lib/mission/ src/core/ros_px4_template_core/nodes/mission_manager.py src/core/ros_px4_template_core/nodes/offboard_controller.py`
> Plans 030 (disarm latch), 040 (counter rename), and 041 (yaw) legitimately
> touch these files first - reconcile with their diffs. Any OTHER drift is a
> STOP condition.

## Status

- **Priority**: P1 (direction: competition capability)
- **Effort**: M/L
- **Risk**: MED-HIGH (commands a real PX4 landing; live verification is mandatory before marking DONE)
- **Depends on**: plans/030-fix-auto-arm-disarm-latch.md (the no-rearm latch this composes with)
- **Category**: feature
- **Planned at**: commit `ead4cc6`, 2026-07-06

## Why this matters

Precision landing on a visual target is the single most common scored element
across drone competitions (land on the pad, land on the moving/marked
platform). The stack already has every ingredient: marker detection with
metric body-frame offsets, a `center_on_marker` behavior that visually servos
over the marker, and a reserved `Land` command in the vocabulary
(`lib/mission/commands.py:22-23`: "Reserved for the center_land follow-on;
not emitted by v1 behaviors"). What is missing is the last mile: a behavior
that descends while centered, a mission_manager that executes `Land` instead
of silently dropping it, and a controller that hands control back to PX4's
lander without immediately yanking the vehicle back into OFFBOARD.

## Current state

- `lib/mission/commands.py` - `Land` is an empty frozen dataclass; the
  `Command` union already includes it.
- `lib/mission/behaviors.py:94-118` - `center_on_marker`: latest detection ->
  `marker_world_from_drone` -> `GoTo(tx, ty, z)` at fixed `altitude_m`;
  signals `centering_error`, `centered`, `hold_complete`. `center_land`
  reuses this XY logic with a descending z.
- `lib/mission/guards.py` - no `disarmed` guard yet (`armed_at_altitude` is
  the only arming-related one).
- `nodes/mission_manager.py:184-188` - `_tick` only handles `GoTo`;
  `Hold`/`Land` fall through and the last `GoTo` target keeps being
  republished. No `/drone/land_command` publisher exists.
- `nodes/offboard_controller.py`:
  - `_vehicle_command(command, **params)` (lines 337-353) can send any
    `VehicleCommand`; `VehicleCommand.VEHICLE_CMD_NAV_LAND` (= 21) is
    available on the imported px4_msgs type.
  - The FSM re-commands OFFBOARD whenever `nav_state != 14` and auto_arm is
    on (`lib/offboard_fsm.py:67-69`) - this is the "yank back mid-landing"
    hazard: PX4's NAV_LAND switches nav_state to AUTO_LAND, and an active
    auto_arm FSM would immediately send DO_SET_MODE OFFBOARD again.
  - After plan 030: `self._disarm_latched` exists; set on observed disarm,
    honored in `_update_state_machine`, cleared by an explicit
    `auto_arm=true` param set.
- `lib/events.py` - canonical event names; add new ones here.
- Wire/docs contract: every new topic needs a row in `docs/TOPICS.md` and the
  node docstring interface block (`just log topics` enforces presence).
- Schema: `center_land` and `disarmed` are NEW registry names ->
  `schemas/mission.schema.json` must be regenerated
  (`just mission schema > schemas/mission.schema.json`); a unit test fails on
  drift.
- Scenario plumbing: `tests/scenarios/05_aruco_hover.py` publishes SYNTHETIC
  camera frames (it renders an ArUco marker into an image and publishes
  `/camera/image_raw` + `/camera/camera_info` itself), so a landing scenario
  needs no Gazebo camera. Scenarios are grouped by `(sim_vision, sim_overlay)`
  from `tests/capabilities.toml`; overlays live in `config/params/overlays/`.
- Missions: model `config/missions/precision_land.yaml` on
  `config/missions/marker_hover.yaml` (schema directive line, safety tier,
  `terminal:`).

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Behavior/guard tests | `uv run pytest tests/unit/test_mission_behaviors.py tests/unit/test_mission_guards.py -q` | all pass |
| Schema regen | `just mission schema > schemas/mission.schema.json` | drift test passes afterwards |
| Mission validation | `just mission validate precision_land` | OK |
| Full gate | `just check` | exit 0 |
| Live scenario (operator) | `just scenario 07_precision_land` | PASS |

## Scope

**In scope**:
- `src/core/ros_px4_template_core/lib/mission/behaviors.py` (`center_land`)
- `src/core/ros_px4_template_core/lib/mission/guards.py` (`disarmed`)
- `src/core/ros_px4_template_core/lib/events.py` (new event names)
- `src/core/ros_px4_template_core/nodes/mission_manager.py` (execute `Land`)
- `src/core/ros_px4_template_core/nodes/offboard_controller.py` (land latch)
- `config/missions/precision_land.yaml`, `config/params/overlays/precision_land.yaml` (create)
- `schemas/mission.schema.json` (regenerated)
- `tests/unit/test_mission_behaviors.py`, `tests/unit/test_mission_guards.py`
- `tests/scenarios/07_precision_land.py`, `tests/capabilities.toml`
- `docs/TOPICS.md`, `docs/MISSIONS.md`

**Out of scope**:
- Moving-platform tracking, velocity feed-forward - static pad only.
- PX4 param tuning for descent (`MPC_LAND_SPEED` etc.) - stock landing.
- `Hold` command execution (still unhandled; only `Land` gains semantics).
- Any change to `lib/offboard_fsm.py` - the suppression happens in the node's
  input computation, same pattern as plan 030.

## Git workflow

- Branch: `advisor/042-precision-landing`
- Commit style: `feat(mission): precision landing via center_land behavior and Land execution`
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: `center_land` behavior

In `lib/mission/behaviors.py`, add (after `center_on_marker`, reusing its
XY logic):

```python
@behavior("center_land")
def center_land(scratch: dict, inputs: Inputs, params: dict) -> BehaviorResult:
    """Visually servo over the marker, descend while centered, hand off to PX4 land."""
```

Params (defaults): `target_id` (None = any), `tolerance_m` (0.3),
`descent_rate_m_s` (0.4), `land_altitude_m` (0.7), `min_altitude_m` (0.3).

Logic per tick:

1. Track marker XY exactly like `center_on_marker` (latest detection ->
   `marker_world_from_drone` -> stash `tx`/`ty` in scratch; fall back to the
   stash when the detection blinks).
2. `err = hypot(dx, dy)`; `centered = err <= tolerance_m`.
3. z command: initialize `scratch["z_cmd"]` to `inputs.pose_enu[2]` on entry.
   When `centered`, step it down by `descent_rate_m_s * dt` where
   `dt = inputs.now - scratch.get("last_now", inputs.now)`; when not centered,
   hold `z_cmd` (do not climb back). Always store
   `scratch["last_now"] = inputs.now`. Clamp `z_cmd` to `min_altitude_m`.
4. When `inputs.pose_enu[2] <= land_altitude_m and centered`: return
   `BehaviorResult(Land(), {"centering_error": err, "centered": centered,
   "land_commanded": True})`.
5. Otherwise return
   `BehaviorResult(GoTo(tx, ty, scratch["z_cmd"]), {"centering_error": err,
   "centered": centered, "land_commanded": False})`.

Import `Land` alongside `GoTo` at the top.

Unit tests in `tests/unit/test_mission_behaviors.py` (pure - build `Inputs`
and detections by hand, model on the existing `center_on_marker` tests):

- centered at altitude -> `GoTo` with z strictly decreasing across ticks with
  advancing `now`.
- not centered -> z holds (no descent, no climb).
- centered at `pose_enu[2] <= land_altitude_m` -> command is `Land` and signal
  `land_commanded` is True.
- detection lost mid-descent -> keeps last tx/ty (scratch fallback), still
  descends only if the `centered` computation over the stashed point allows.

### Step 2: `disarmed` guard

In `lib/mission/guards.py`:

```python
@guard("disarmed")
def disarmed(inputs: Inputs, signals: dict, params: dict) -> bool:
    return not inputs.armed
```

Unit tests in `tests/unit/test_mission_guards.py`: armed -> False,
disarmed -> True.

**Verify**: `uv run pytest tests/unit/test_mission_behaviors.py tests/unit/test_mission_guards.py -q` -> all pass

### Step 3: Regenerate the schema

`just mission schema > schemas/mission.schema.json`

**Verify**: `uv run pytest tests/unit -q -k schema` -> the drift test passes;
`git diff schemas/mission.schema.json` shows `center_land` and `disarmed`
added to the enums and nothing else.

### Step 4: `mission_manager` executes `Land`

1. Add publisher in `__init__` (next to `_pub_target`):
   `self._pub_land = self.create_publisher(Empty, "/drone/land_command", _RELIABLE_QOS)`
   with `from std_msgs.msg import Empty`.
2. Add `self._land_sent = False` state field.
3. In `_tick`, extend the command handling:

```python
        if isinstance(command, GoTo):
            self._last_target = (command.x, command.y, command.z)
        if isinstance(command, Land) and not self._land_sent:
            self._land_sent = True
            self._pub_land.publish(Empty())
            self.slog.event(events.LAND_COMMAND_SENT_MISSION)
        if not isinstance(command, Land):
            self._publish_target(self._last_target)
        self._publish_status(inputs, now)
        self._publish_markers(self._last_target)
```

   Import `Land` next to `GoTo` (line 32) and `events`. Skipping
   `_publish_target` during `Land` matters: a fresh target during PX4's
   descent would fight the lander if anything re-entered OFFBOARD. (If plan
   041 landed first, `_publish_target` takes a yaw argument - reconcile.)
4. Update the module docstring's ROS 2 Interface block: add
   `/drone/land_command [std_msgs/Empty]` under Publishers.
5. Add to `lib/events.py` (mission section):
   `LAND_COMMAND_SENT_MISSION = "LAND_COMMAND_SENT_MISSION"`.

**Verify**: `uv run ruff check src/core/ros_px4_template_core/nodes/mission_manager.py` -> exit 0

### Step 5: `offboard_controller` hands off to PX4 land

1. Subscribe in `__init__` (with the other `/drone/*` subscriptions):
   `self.create_subscription(Empty, "/drone/land_command", self._land_cb, _RELIABLE_QOS)`
   (`from std_msgs.msg import Empty`).
2. Add `self._landing = False` state field, and the callback:

```python
    def _land_cb(self, _msg: Empty) -> None:
        if self._landing:
            return
        self._landing = True
        self._disarm_latched = True
        self._vehicle_command(VehicleCommand.VEHICLE_CMD_NAV_LAND)
        self.slog.event(events.LAND_COMMAND_RECEIVED)
```

   Setting `_disarm_latched` (from plan 030) is the suppression: the per-tick
   `self._auto_arm = param and not self._disarm_latched` computation turns the
   FSM off, so it stops re-commanding OFFBOARD while PX4's AUTO_LAND runs, and
   there is no auto-rearm after touchdown. Trajectory setpoints stop flowing
   automatically because `_control_loop` only publishes them when
   `nav_state == NAV_STATE_OFFBOARD`.
3. Note the interplay with `_common.trigger_auto_arm` (e2e re-arm): an
   explicit `auto_arm=true` param set clears the latch by design (plan 030
   Step 3) - also clear `self._landing` in that same param callback branch so
   a later scenario in the same sim boot can land again.
4. Add to `lib/events.py` (arming section):
   `LAND_COMMAND_RECEIVED = "LAND_COMMAND_RECEIVED"`.
5. Update the module docstring interface block: add `/drone/land_command`
   under Subscriptions.

**Verify**: `uv run ruff check src/core/ros_px4_template_core/nodes/offboard_controller.py` -> exit 0

### Step 6: Mission YAML + overlay + docs

`config/missions/precision_land.yaml` (keep the schema directive line):

```yaml
# yaml-language-server: $schema=../../schemas/mission.schema.json
# Fly to the marker area, center over it, descend, and hand off to PX4 land.
mission:
  initial: takeoff
  safety:
    - {guard: estimate_invalid, to: hold_safe}
    - {guard: inputs_stale, params: {t: 1.0}, to: hold_safe}
  states:
    takeoff:   {behavior: hold, params: {z: 3.0}}
    approach:  {behavior: follow_waypoints, params: {waypoints: [[8.0, 0.0, 3.0]], tolerance_m: 0.6, hold_s: 1.0}}
    land:      {behavior: center_land, params: {target_id: 0, tolerance_m: 0.3, descent_rate_m_s: 0.4, land_altitude_m: 0.7}}
    done:      {behavior: hold}
    hold_safe: {behavior: hold}
  transitions:
    - {from: takeoff,  guard: armed_at_altitude,                    to: approach}
    - {from: approach, guard: marker_stable, params: {id: 0, n: 5}, to: land}
    - {from: approach, guard: waypoints_done,                       to: land}
    - {from: land,     guard: disarmed,                             to: done}
  terminal: [done]
```

(`[8.0, 0.0, 3.0]` matches marker 0's pose in `config/markers.yaml`. The
`done: hold` terminal never actuates: the vehicle is disarmed and the
controller's FSM is latched off; the state exists so the FSM has a clean
terminal.)

`config/params/overlays/precision_land.yaml` (model on
`config/params/overlays/marker_hover.yaml` - auto_arm true, mission_file
pointed at the new mission, `marker_localizer.enabled: false`).

Docs:

- `docs/TOPICS.md`: publisher row for `/drone/land_command`
  (`std_msgs/msg/Empty`, pub, `mission_manager`), subscription-table row
  (`offboard_controller`), and mark it like other always-on topics (it exists
  regardless of vision; the message only fires in landing missions - if
  `just log topics` requires presence, the topic exists as soon as both nodes
  are up, which is always).
- `docs/MISSIONS.md`: behaviors table row for `center_land` (params +
  signals), guards table row for `disarmed`, and add `07_precision_land` to
  the scenario coverage table.

**Verify**: `just mission validate precision_land` -> OK

### Step 7: Scenario `tests/scenarios/07_precision_land.py`

Scaffold with `just scenario-new 07_precision_land`, then model the body on
`tests/scenarios/05_aruco_hover.py`:

- Reuse 05's synthetic-camera approach: render the marker (id 0) into
  published `/camera/image_raw` frames positioned so the detector computes a
  body-frame offset consistent with the marker sitting at world (8, 0, 0)
  relative to the drone's current `/drone/odom` pose (05 already contains
  this math; copy its helper).
- Track: mission phase reaching `land` (from `/drone/mission_status`),
  `/drone/odom` z decreasing below ~1.0 m while |xy - (8,0)| stays within
  0.6 m, then disarm observed (from `/drone/controller_status` `armed`
  False), then phase `done`.
- `done()` predicate: disarmed AND phase == `done`.
- FAIL detail dict must carry the funnel: `entered_land`, `min_z_seen`,
  `xy_err_at_min_z`, `disarmed_seen` (plan 032's rich-detail convention).
- End with `_common.write_report` passing a real detail, e.g.
  `landed xy_err=0.21m` on PASS.
- `tests/capabilities.toml` entry:

```toml
[capabilities.precision_land]
description = "Vehicle centers on the marker, descends, and PX4 lands it; no auto-rearm"
status = "untested"
platforms = ["sim"]
scenario_file = "07_precision_land.py"
sim_vision = "aruco"
sim_overlay = "precision_land"
```

**Verify**: `uv run ruff check tests/scenarios/07_precision_land.py` -> exit 0

### Step 8: Full gate + live verification (operator-gated)

1. `just check` -> exit 0.
2. Operator, in a sim-capable shell: `just scenario 07_precision_land` ->
   PASS. Watch `just log tail` for the arc:
   `LAND_COMMAND_SENT_MISSION` -> `LAND_COMMAND_RECEIVED` ->
   PX4 `Landing detected` (px4 source) -> `AUTO_ARM_DISABLED_ON_DISARM`
   with NO later `ARM_COMMAND_SENT` (the no-rearm property).
3. Regression: `just test e2e` -> exit 0 (all prior scenarios PASS; the new
   subscription/publisher must not disturb them).
4. On PASS: `just cap mark precision_land sim`.

If you cannot run a sim, complete steps 1-7, run `just check`, and STOP
reporting live verification pending (matches plans 005/006/030 handling).

## Test plan

Unit: `center_land` descent/hold/handoff/blink cases, `disarmed` guard, the
schema drift test. Live: scenario 07 (the funnel above) plus the e2e
regression. The no-rearm property is asserted by log inspection in Step 8.2.

## Done criteria

- [ ] `uv run pytest tests/unit -q` passes (new behavior/guard tests included)
- [ ] `just mission validate precision_land` -> OK
- [ ] `rg -n "land_command" docs/TOPICS.md src/core/ros_px4_template_core/nodes/mission_manager.py src/core/ros_px4_template_core/nodes/offboard_controller.py` -> row + both docstrings + code
- [ ] `git diff schemas/mission.schema.json` shows only the two enum additions
- [ ] `just check` exits 0
- [ ] Live: `just scenario 07_precision_land` PASS and `just test e2e` exit 0 (or reported as pending operator sign-off)
- [ ] `tests/capabilities.toml` has the `precision_land` entry; `just cap mark precision_land sim` run after the live PASS
- [ ] `plans/README.md` status row updated

## STOP conditions

- Plan 030 has not landed (`_disarm_latched` absent from
  `offboard_controller.py`) - the suppression design depends on it; report
  the dependency.
- During live verification the vehicle re-enters OFFBOARD after NAV_LAND
  (log shows `OFFBOARD_MODE_COMMAND` after `LAND_COMMAND_RECEIVED`) - the
  latch is not suppressing; STOP, `just stop`, report the log excerpt.
- PX4 rejects NAV_LAND (ack DENIED in the log) - report the ack result;
  do not retry-loop the command.
- Scenario 05/06 regress in e2e - the new center_land/scratch changes leaked
  into `center_on_marker`; report.

## Maintenance notes

- Moving-platform landing = replace the scratch tx/ty stash with a velocity
  estimate; the wire contract (`Land` -> `/drone/land_command` -> NAV_LAND)
  already supports it.
- Reviewer: check `_land_cb` is idempotent (guard on `self._landing`), the
  param-callback also clears `_landing`, and `_publish_target` is skipped
  while the command is `Land`.
- `Hold` remains unexecuted vocabulary; if a behavior starts emitting it,
  mission_manager needs a case (today it would republish `_last_target`,
  which is coincidentally hold-like).
