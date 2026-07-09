# Plan 041: Yaw control end to end (mission YAML to TrajectorySetpoint.yaw)

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report - do not improvise. When done, update the status row for this plan
> in `plans/README.md` - unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat ead4cc6..HEAD -- src/core/ros_px4_template_core/lib/frames.py src/core/ros_px4_template_core/lib/mission/behaviors.py src/core/ros_px4_template_core/nodes/mission_manager.py src/core/ros_px4_template_core/nodes/offboard_controller.py`
> If any changed, compare the "Current state" excerpts before proceeding; on
> a mismatch, treat it as a STOP condition. (Plan 040 renames a counter in
> `offboard_controller.py`; that rename is expected drift - reconcile and
> continue.)

## Status

- **Priority**: P1 (direction: competition capability)
- **Effort**: M
- **Risk**: MED (touches the PX4 boundary; NaN-yaw default must be preserved exactly)
- **Depends on**: none (plan 042 builds on the same files; land this first)
- **Category**: feature
- **Planned at**: commit `ead4cc6`, 2026-07-06

## Why this matters

Competition tasks routinely require pointing the vehicle: aim a fixed camera
at a target, align a gripper/dropper, fly a corridor nose-first, present a
marker to a judge camera. Today the stack is position-only end to end: the
`GoTo` command already HAS a `yaw` field (`lib/mission/commands.py:13`) but no
behavior sets it, `mission_manager` publishes a hardcoded identity quaternion,
and `offboard_controller` always sends `TrajectorySetpoint.yaw = NaN` (PX4
"hold current heading"). This plan wires the existing field through the whole
chain with a wire-format sentinel that keeps "yaw free" the default.

## Current state

- `lib/mission/commands.py:9-13` - `GoTo(x, y, z, yaw: float | None = None)`.
  The field exists and is dead.
- `lib/mission/behaviors.py` - all five behaviors emit `GoTo` without yaw.
  `hold` (lines 24-32) stashes x/y/z in scratch on entry;
  `follow_waypoints` (lines 56-64) parses `waypoints` as
  `[tuple(map(float, p)) for p in params.get("waypoints", [])]` and emits
  `GoTo(*cur)`; `_step_waypoints` (lines 35-53) measures
  `math.dist(inputs.pose_enu, wps[idx])` - it needs 3-element tuples.
- `nodes/mission_manager.py`:
  - `_tick` lines 184-186: `if isinstance(command, GoTo): self._last_target =
    (command.x, command.y, command.z)` then `self._publish_target(self._last_target)`.
  - `_publish_target` lines 190-198: always `msg.pose.orientation.w = 1.0`
    (identity quaternion; x/y/z default 0).
  - The pre-odom early return at lines 172-174 also calls `_publish_target`.
- `nodes/offboard_controller.py`:
  - module docstring line 3: "Yaw is omitted (NaN) for position-only missions
    so PX4 holds current heading."
  - `_target_pose_cb` lines 141-150 reads only `msg.pose.position`.
  - `_publish_position_setpoint` lines 328-334 sets `msg.yaw = float("nan")`
    and `msg.yawspeed = float("nan")`.
- `lib/frames.py` - has `enu_yaw_from_heading` (lines 48-51:
  `pi/2 - heading_ned`, wrapped via `atan2(sin, cos)`),
  `enu_yaw_from_quaternion` (54-56), `enu_quaternion_from_yaw` (59-61).
  There is NO inverse helper ENU yaw -> NED heading yet. The transform is an
  involution: `heading_ned = pi/2 - yaw_enu` with the same wrap.
- Tests: `tests/unit/test_frames.py`, `tests/unit/test_mission_behaviors.py`
  exist; extend both.
- Schema note: `tools/mission_cli.py:build_schema` enumerates behavior/guard
  NAMES only; `params` is a free-form object. This plan adds no new names, so
  NO schema regeneration is needed.
- PX4 convention: `TrajectorySetpoint.yaw` is NED heading in radians
  (0 = North, clockwise positive); NaN means "do not control yaw".

## Wire contract (the one design decision - implement exactly this)

`/drone/target_pose` orientation:

- **All-zero quaternion** (w=x=y=z=0, an invalid rotation) = "yaw free";
  controller sends `yaw = NaN`.
- **Any valid quaternion** (norm near 1) = commanded ENU yaw; controller
  extracts yaw and sends it converted to NED.

Rationale: the identity quaternion is a REAL yaw (0 rad = East), so it cannot
mean "ignore". The all-zero quaternion is not a rotation at all, is trivially
detectable (`norm^2 < 0.25` threshold), and is what a zero-initialized
message contains - a publisher that never thinks about yaw gets yaw-free
behavior automatically.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Frame tests | `uv run pytest tests/unit/test_frames.py -q` | all pass |
| Behavior tests | `uv run pytest tests/unit/test_mission_behaviors.py -q` | all pass |
| Mission validation | `just mission validate demo` | OK |
| Full gate | `just check` | exit 0 |
| Live check (operator) | see Step 7 | vehicle points along commanded yaw |

## Scope

**In scope**:
- `src/core/ros_px4_template_core/lib/frames.py` (new `heading_ned_from_enu_yaw`)
- `src/core/ros_px4_template_core/lib/mission/behaviors.py` (`hold`,
  `follow_waypoints` gain optional yaw)
- `src/core/ros_px4_template_core/nodes/mission_manager.py`
- `src/core/ros_px4_template_core/nodes/offboard_controller.py`
- `tests/unit/test_frames.py`, `tests/unit/test_mission_behaviors.py`
- `docs/MISSIONS.md`, `docs/TOPICS.md` (contract notes)

**Out of scope**:
- Yaw-rate control (`yawspeed` stays NaN always).
- `search_lawnmower`, `center_on_marker`, `goto_origin` - yaw-free (follow-ups
  can add tangent-yaw to the lawnmower later).
- `schemas/mission.schema.json` (no new behavior/guard names).
- Ramping/slewing yaw in the controller; PX4's own yaw rate limiting applies.

## Git workflow

- Branch: `advisor/041-yaw-control`
- Commit style: `feat(control): command yaw end to end via GoTo.yaw and target_pose orientation`
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: `heading_ned_from_enu_yaw` in `frames.py`

Add directly below `enu_yaw_from_heading` (match its shape and docstring
style):

```python
def heading_ned_from_enu_yaw(yaw_enu: float) -> float:
    """ENU yaw (0=East, CCW+) -> PX4 heading (NED yaw: 0=North, CW+), wrapped."""
    heading = math.pi / 2.0 - yaw_enu
    return math.atan2(math.sin(heading), math.cos(heading))
```

Tests in `tests/unit/test_frames.py`:

- round-trip: for yaw in `[-pi, -2, -pi/2, 0, pi/2, 2, pi]`,
  `enu_yaw_from_heading(heading_ned_from_enu_yaw(y))` == y (use
  `math.isclose`, and compare wrapped values for the +/-pi endpoint).
- anchors: ENU 0 (East) -> NED pi/2; ENU pi/2 (North) -> NED 0.

**Verify**: `uv run pytest tests/unit/test_frames.py -q` -> all pass

### Step 2: Behaviors emit yaw

In `lib/mission/behaviors.py` (YAML speaks degrees; commands carry radians):

1. `hold`: read `yaw_deg = params.get("yaw_deg")` once at entry alongside
   x/y/z (store `scratch["yaw"] = math.radians(float(yaw_deg))` or `None`).
   Emit `GoTo(scratch["x"], scratch["y"], scratch["z"], yaw=scratch["yaw"])`.
2. `follow_waypoints`: accept waypoint entries of length 3 (`[x, y, z]`) or
   4 (`[x, y, z, yaw_deg]`). Parse into positions
   `wps = [tuple(map(float, p[:3])) for p in raw]` (so `_step_waypoints`
   distance math is untouched) and a parallel
   `yaws = [math.radians(float(p[3])) if len(p) > 3 else None for p in raw]`.
   Emit `GoTo(*cur, yaw=yaws[min(idx, len(yaws) - 1)] if yaws else None)`.

`Hold`/`Land` and all other behaviors unchanged.

Tests in `tests/unit/test_mission_behaviors.py`:

- `hold` with `yaw_deg: 90` emits `GoTo.yaw == pytest.approx(math.pi / 2)`;
  without the param emits `yaw is None`.
- `follow_waypoints` with mixed `[[0,0,3], [5,0,3,180]]` emits `yaw None` at
  index 0 and `pi` at index 1; 3-element-only lists still work (regression).

**Verify**: `uv run pytest tests/unit/test_mission_behaviors.py -q` -> all pass

### Step 3: `mission_manager` publishes the contract

1. Add `self._last_yaw: float | None = None` next to `_last_target` (line 84).
2. In `_tick`: inside the existing `if isinstance(command, GoTo):` also set
   `self._last_yaw = command.yaw`. Pass it:
   `self._publish_target(self._last_target, self._last_yaw)`. The pre-odom
   early return passes `None`.
3. `_publish_target(self, target, yaw_enu: float | None = None)`: replace the
   hardcoded `msg.pose.orientation.w = 1.0` with:
   - `yaw_enu is None`: leave orientation at message defaults (all zeros) -
     the sentinel.
   - else: `qw, qx, qy, qz = enu_quaternion_from_yaw(yaw_enu)` and assign all
     four fields. Import `enu_quaternion_from_yaw` next to the existing
     `enu_yaw_from_quaternion` import (line 31).
4. Update the docstring's ROS 2 Interface block only if it mentions
   orientation (it does not; leave it).

**Verify**: `uv run ruff check src/core/ros_px4_template_core/nodes/mission_manager.py` -> exit 0

### Step 4: `offboard_controller` consumes the contract

1. Init `self._target_yaw_enu: float | None = None` near `_setpoint_enu`
   (line 85).
2. In `_target_pose_cb`: after reading position, read `q = msg.pose.orientation`;
   `if q.w * q.w + q.x * q.x + q.y * q.y + q.z * q.z > 0.25:` set
   `self._target_yaw_enu = enu_yaw_from_quaternion(q.w, q.x, q.y, q.z)`,
   else `None`. (0.25 = norm 0.5 squared; cleanly separates all-zero from
   unit quaternions.)
3. In `_publish_position_setpoint`: replace `msg.yaw = float("nan")` with
   `msg.yaw = heading_ned_from_enu_yaw(self._target_yaw_enu) if
   self._target_yaw_enu is not None else float("nan")`. `yawspeed` stays NaN.
   Extend the imports from `lib.frames` (line 27).
4. Update the module docstring line 3 to: "Yaw is commanded only when
   `/drone/target_pose` carries a valid (non-zero) quaternion; otherwise
   TrajectorySetpoint.yaw is NaN and PX4 holds current heading."

Frame conversion stays at the PX4 boundary (invariant 2/5 in AGENTS.md):
mission code speaks ENU yaw; only this function emits NED.

**Verify**: `uv run ruff check src/core/ros_px4_template_core/nodes/offboard_controller.py` -> exit 0

### Step 5: Docs

1. `docs/MISSIONS.md` behaviors table: `hold` params gain `yaw_deg (none)`;
   `follow_waypoints` waypoints become "list of `[x,y,z]` or `[x,y,z,yaw_deg]`".
   Add one sentence under the table: "Yaw is optional everywhere: omitted
   means PX4 holds current heading. `yaw_deg` is ENU degrees (0 = East,
   CCW positive)."
2. `docs/TOPICS.md`: in the QoS/notes section add one line documenting the
   `/drone/target_pose` orientation sentinel (all-zero quaternion = yaw free;
   valid quaternion = commanded ENU yaw).

**Verify**: `rg -n "yaw_deg" docs/MISSIONS.md` -> matches;
`rg -n "quaternion" docs/TOPICS.md` -> the sentinel note

### Step 6: Full gate + mission validation

**Verify**: `just check` -> exit 0; `just mission validate hover` and
`just mission validate demo` -> OK (yaw params are optional; existing
missions unchanged).

### Step 7: Live verification (operator-gated)

Requires a sim host; coordinate with the operator, do not run unattended.

1. Add `yaw_deg: 90` to the hold state's params in a COPY of
   `config/missions/hover.yaml` (e.g. `config/missions/hover_yaw.yaml` with
   the schema directive line kept; delete the copy after the check or keep it
   as a demo - operator's call).
2. `just sim --overlay auto_arm` with `mission_file` pointed at the copy via
   a temporary overlay, or simply
   `ros2 param set /mission_manager mission_file config/missions/hover_yaw.yaml`
   before arming (mission file is read at node start; if the param is only
   read in `__init__`, relaunch instead - check `nodes/mission_manager.py:63`).
3. Confirm: `just log tail` shows the mission holding, and
   `ros2 topic echo /fmu/in/trajectory_setpoint --once` shows `yaw` near 0.0
   (ENU 90 deg = North = NED heading 0), not NaN.
4. Regression: run `just scenario 01_arm_takeoff` and `just scenario
   02_hover_hold` (yaw-free missions) -> PASS, and their
   `/fmu/in/trajectory_setpoint` yaw is NaN.

**Verify**: both checks as described; report the observed yaw values.

## Test plan

Unit: frames round-trip + anchors (Step 1), behavior yaw emission + 3-element
regression (Step 2). Integration: Step 7's live check covers
mission_manager -> controller -> PX4. The critical regression surface is
"yaw-free missions still send NaN" - covered by Step 7.4 and by the sentinel
being the zero-initialized default.

## Done criteria

- [ ] `uv run pytest tests/unit/test_frames.py tests/unit/test_mission_behaviors.py -q` all pass (new tests included)
- [ ] `rg -n "heading_ned_from_enu_yaw" src/core/ros_px4_template_core/lib/frames.py src/core/ros_px4_template_core/nodes/offboard_controller.py` -> definition + one use
- [ ] `rg -n "orientation.w = 1.0" src/core/ros_px4_template_core/nodes/mission_manager.py` -> no match in `_publish_target` (the `_publish_markers` RViz arrow at line 221 KEEPS its `w = 1.0`)
- [ ] `just check` exits 0
- [ ] Step 7 live checks reported (or explicitly deferred by the operator)
- [ ] `git status` shows only in-scope files modified
- [ ] `plans/README.md` status row updated

## STOP conditions

- Excerpts do not match (beyond plan 040's counter rename).
- Scenario 01/02 regress in Step 7.4 - the NaN default broke; revert and
  report rather than tuning thresholds live.
- Any temptation to convert frames anywhere except
  `_publish_position_setpoint` - that violates the ENU/NED boundary invariant;
  stop and re-read the design.

## Maintenance notes

- `center_on_marker`/`search_lawnmower` can adopt yaw later (face-the-marker,
  tangent-yaw) by setting `GoTo.yaw` - the wire contract needs no change.
- Plan 042 (precision landing) assumes this wire contract exists but does not
  depend on it; either merge order works, 041-first keeps diffs cleaner.
- Reviewer: check the sentinel threshold is on the SQUARED norm (0.25) and
  that `_publish_markers`'s RViz-only quaternion was not touched.
