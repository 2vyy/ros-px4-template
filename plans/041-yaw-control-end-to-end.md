# Plan 041: Command yaw from mission YAML through PX4 `TrajectorySetpoint`

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If a STOP condition occurs, stop and report. Do not improvise.
> When done, update this plan's row in `plans/README.md` unless a reviewer
> explicitly owns the index update.
>
> **Drift check (run first)**:
> `git diff --stat e05d19b..HEAD -- src/core/ros_px4_template_core/lib/frames.py src/core/ros_px4_template_core/lib/target_pose.py src/core/ros_px4_template_core/lib/mission/behaviors.py src/core/ros_px4_template_core/nodes/mission_manager.py src/core/ros_px4_template_core/nodes/offboard_controller.py tests/unit/test_frames.py tests/unit/test_target_pose.py tests/unit/test_mission_behaviors.py config/missions/yaw_demo.yaml config/params/overlays/yaw_demo.yaml tests/scenarios/07_yaw_control.py tests/capabilities.toml docs/MISSIONS.md docs/TOPICS.md`
>
> Also run `git diff --stat -- <the same paths>` so uncommitted changes are
> visible. If either command reports drift, compare the current code with the
> excerpts below. Stop on a semantic mismatch.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MED (touches the PX4 frame boundary and yaw-free default)
- **Depends on**: none; execute before plans 044 and 042 to avoid shared-file conflicts
- **Category**: direction
- **Planned at**: commit `e05d19b`, 2026-07-09

## Why this matters

Competition tasks need deliberate heading control for cameras, grippers,
corridors, and judged poses. `GoTo` already carries optional ENU yaw, but no
behavior sets it and `offboard_controller` always sends yaw as NaN. This plan
wires yaw end to end while preserving the existing contract: omitted yaw
means PX4 does not control heading.

## Current state

- `lib/mission/commands.py:9-13` defines `GoTo(x, y, z, yaw=None)`.
- `lib/mission/behaviors.py:24-64` emits position-only `GoTo` commands.
  `follow_waypoints` currently assumes every entry has exactly three values.
- `nodes/mission_manager.py:205-219` stores only XYZ and publishes identity
  orientation on `/drone/target_pose`.
- `nodes/offboard_controller.py:153-159` reads only target position;
  `_publish_position_setpoint` sends `TrajectorySetpoint.yaw = NaN`.
- `lib/frames.py` has NED heading to ENU yaw and quaternion helpers, but no
  ENU yaw to NED heading helper.
- `TrajectorySetpoint.msg` states that NaN means the state is uncontrolled.
- `tests/scenarios/` and `tests/capabilities.toml` are the required live
  acceptance and capability-recording surfaces.

## Design decisions

### YAML and internal units

- YAML uses `yaw_deg` in ENU: 0 degrees is East, positive is counter-clockwise.
- `GoTo.yaw` stores ENU radians.
- Only `offboard_controller` converts ENU yaw to PX4 NED heading.

### `/drone/target_pose` optional-yaw contract

- All-zero quaternion means yaw is omitted. The controller sends NaN.
- A finite, near-unit quaternion means commanded ENU yaw.
- A non-zero malformed quaternion is treated as yaw omitted and produces one
  rate-limited diagnostic, never an exception from a ROS callback.

The identity quaternion cannot be the sentinel because it is a real ENU yaw
of zero. Keep the invalid sentinel isolated in a pure codec so node code does
not duplicate norm thresholds or malformed-input handling.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Unit tests | `uv run pytest tests/unit/test_frames.py tests/unit/test_target_pose.py tests/unit/test_mission_behaviors.py -q` | all pass |
| Mission validation | `just mission validate yaw_demo` | `OK` |
| Full gate | `just check` | exit 0 |
| Live acceptance | `just scenario 07_yaw_control` | PASS with observed yaw |
| Regression | `just scenario 01_arm_takeoff` | PASS with yaw-free setpoints |

## Scope

**In scope**:

- `src/core/ros_px4_template_core/lib/frames.py`
- `src/core/ros_px4_template_core/lib/target_pose.py` (create, pure codec)
- `src/core/ros_px4_template_core/lib/mission/behaviors.py`
- `src/core/ros_px4_template_core/nodes/mission_manager.py`
- `src/core/ros_px4_template_core/nodes/offboard_controller.py`
- `tests/unit/test_frames.py`
- `tests/unit/test_target_pose.py` (create)
- `tests/unit/test_mission_behaviors.py`
- `config/missions/yaw_demo.yaml` (create)
- `config/params/overlays/yaw_demo.yaml` (create)
- `tests/scenarios/07_yaw_control.py` (create)
- `tests/capabilities.toml`
- `docs/MISSIONS.md`, `docs/TOPICS.md`
- `plans/README.md` status only

**Out of scope**:

- Yaw-rate control. `TrajectorySetpoint.yawspeed` remains NaN.
- Yaw slewing or ramping. PX4 owns rate limiting.
- Automatic tangent yaw for search paths.
- Changes to `px4_msgs`, schemas, PX4 parameters, or files under `PX4_DIR`.

## Git workflow

- Branch: `advisor/041-yaw-control`
- Commit: `feat(control): command mission yaw end to end`
- Do not push or open a PR without operator instruction.

## Steps

### Step 1: Add the ENU yaw to NED heading inverse

Add `heading_ned_from_enu_yaw` next to `enu_yaw_from_heading` in
`lib/frames.py`. Wrap with `atan2(sin(x), cos(x))`, matching the existing
helper. Add property-style round-trip coverage and cardinal anchors to
`tests/unit/test_frames.py`:

- ENU East 0 to NED East `pi/2`.
- ENU North `pi/2` to NED North 0.
- Representative values round-trip modulo the `-pi`/`pi` equivalence.

**Verify**: `uv run pytest tests/unit/test_frames.py -q` -> all pass.

### Step 2: Add a pure optional-yaw codec

Create `lib/target_pose.py`, with no ROS imports:

- `target_yaw_to_quaternion(yaw_enu: float | None) -> tuple[float, float, float, float]`
  returns `(0, 0, 0, 0)` for `None`, otherwise delegates to
  `enu_quaternion_from_yaw`.
- `target_yaw_from_quaternion(qw, qx, qy, qz) -> float | None`:
  - returns `None` for the all-zero sentinel;
  - returns `None` for non-finite components or a norm outside a documented
    near-unit range;
  - normalizes a near-unit quaternion before extracting ENU yaw.

Tests in `test_target_pose.py` must cover sentinel round-trip, ENU cardinal
yaws, a slightly non-unit valid quaternion, NaN, and a non-zero malformed
quaternion. Do not import `geometry_msgs` in the helper or tests.

**Verify**: `uv run pytest tests/unit/test_target_pose.py -q` -> all pass.

### Step 3: Teach mission behaviors the YAML yaw shape

In `hold`, latch optional `yaw_deg` on state entry and emit it as radians.

In `follow_waypoints`, accept only:

- `[x, y, z]`
- `[x, y, z, yaw_deg]`

Split each entry into a three-element position tuple and a parallel optional
yaw list. Reject any other length with a clear `ValueError` naming the entry
index and expected lengths. `_step_waypoints` must continue receiving only
three-element positions.

Add tests for hold with and without yaw, mixed three/four-element waypoints,
waypoint advancement preserving the matching yaw, and malformed lengths.

**Verify**: `uv run pytest tests/unit/test_mission_behaviors.py -q` -> all pass.

### Step 4: Publish and consume the optional-yaw contract

In `mission_manager`:

1. Add `_last_yaw: float | None = None` next to `_last_target`.
2. Update both fields whenever the command is `GoTo`.
3. Pass yaw into `_publish_target`; pre-odom publication passes `None`.
4. Fill all four quaternion components from `target_yaw_to_quaternion`.
5. Do not change `_publish_markers`; its RViz arrow keeps identity orientation.

In `offboard_controller`:

1. Add `_target_yaw_enu: float | None = None`.
2. Decode every target orientation with `target_yaw_from_quaternion`.
3. Convert a decoded yaw with `heading_ned_from_enu_yaw` only inside
   `_publish_position_setpoint`.
4. Send NaN when yaw is omitted or malformed. Keep yawspeed NaN.
5. Log malformed non-zero orientation once per active malformed interval,
   then log recovery when a valid or zero orientation arrives.

**Verify**:
`uv run ruff check src/core/ros_px4_template_core/lib/target_pose.py src/core/ros_px4_template_core/nodes/mission_manager.py src/core/ros_px4_template_core/nodes/offboard_controller.py`
-> exit 0.

### Step 5: Add a committed live yaw capability

Create `yaw_demo.yaml` with a normal takeoff followed by a hold at 3 m with
`yaw_deg: 90`. Create its overlay with `auto_arm: true` and the mission path.

Scaffold `07_yaw_control.py`. The scenario must:

- observe `/fmu/in/trajectory_setpoint` using `PX4_QOS`;
- observe `/drone/odom` yaw;
- pass only after a finite setpoint yaw is near 0 rad NED and vehicle ENU yaw
  is near `pi/2` for a stable interval;
- report both observed yaw values and errors in `write_report`.

Add capability `yaw_control`, initially `untested`, using overlay `yaw_demo`
and vision `none`.

**Verify**: `just mission validate yaw_demo`; then
`uv run ruff check tests/scenarios/07_yaw_control.py` -> both succeed.

### Step 6: Document the contract

Update the mission behavior table and topic notes:

- `hold` accepts optional `yaw_deg`.
- waypoint entries may contain optional fourth `yaw_deg`.
- omitted yaw means PX4 heading is uncontrolled.
- `/drone/target_pose` all-zero orientation is the documented internal
  sentinel; valid orientation is commanded ENU yaw.

**Verify**: `uv run python tools/check_docs.py` -> `Docs identifier check OK`.

### Step 7: Run gates and live acceptance

1. `just check` -> exit 0.
2. `just scenario 07_yaw_control` -> PASS.
3. `just scenario 01_arm_takeoff` -> PASS.
4. During scenario 01, inspect one trajectory setpoint and confirm yaw is NaN.
5. `just cap mark yaw_control sim` after the PASS.

If no sim is available, finish through `just check`, leave the capability
`untested`, and report live verification pending. Do not mark the plan DONE.

## Test plan

- Pure frame round-trip and cardinal anchors.
- Pure optional-yaw codec including malformed input.
- Behavior tests for omitted, explicit, mixed, and malformed waypoint yaw.
- Live scenario proving mission YAML to target pose to PX4 setpoint to actual
  vehicle yaw.
- Existing yaw-free scenario proving NaN remains the default.

## Done criteria

- [ ] Target-yaw codec has no ROS imports and all tests pass.
- [ ] Waypoint positions passed to `_step_waypoints` remain three-dimensional.
- [ ] ENU-to-NED yaw conversion occurs only in `offboard_controller`.
- [ ] `just mission validate yaw_demo` reports `OK`.
- [ ] `just check` exits 0.
- [ ] `just scenario 07_yaw_control` passes with finite observed yaw values.
- [ ] `just scenario 01_arm_takeoff` passes and emits NaN yaw.
- [ ] `just cap mark yaw_control sim` records the live capability.
- [ ] Only in-scope files changed; the plan index row is updated.

## STOP conditions

- Current source no longer matches the architecture described above.
- The sentinel causes warnings or rejection anywhere outside the explicit
  decoder. Stop and propose a typed message field instead of spreading
  special-case quaternion logic.
- A yaw-free mission emits finite `TrajectorySetpoint.yaw`.
- ENU/NED conversion is needed outside `offboard_controller`.
- The live vehicle rotates opposite the commanded direction. Stop and report
  the observed ENU and NED values; do not compensate with an arbitrary sign.

## Maintenance notes

- Future behaviors opt into heading only by setting `GoTo.yaw` in ENU radians.
- If `/drone/target_pose` becomes a public cross-project API, replace the
  sentinel with an explicit optional-yaw field in a custom message.
- Plan 042 must preserve this codec and `_publish_target(..., yaw)` signature.
