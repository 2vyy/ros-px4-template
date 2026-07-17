# Plan 051: EKF-reset deltas apply to the read path too (pose no longer jumps on reset)

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 01f94c7..HEAD -- src/core/ros_px4_template_core/lib/px4_local_frame.py src/core/ros_px4_template_core/lib/frames.py tests/unit/test_px4_local_frame.py tests/unit/test_frames.py src/core/ros_px4_template_core/nodes/offboard_controller.py`
> On any mismatch with the excerpts below, STOP.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: MED (core frame math; mitigated by characterization tests that pin the no-reset path unchanged)
- **Depends on**: none
- **Category**: bug (frames)
- **Planned at**: commit `01f94c7`, 2026-07-10

## Why this matters

When PX4's EKF resets its position estimate (`xy_reset_counter` /
`z_reset_counter` bump), PX4 shifts all reported NED coordinates by a delta
for the *same physical point*. `Px4LocalFrame` accumulates those deltas and
applies them to the **write path** (setpoint origin) — but not to the **read
path** (the anchored-ENU pose published on `/drone/odom`). After a reset, the
published pose jumps by the delta while setpoints shift the opposite way:
every mission reach/center/geofence check is then computed against a pose the
vehicle is not at. Rare in SITL, real on hardware (EKF resets happen on GPS
glitches and vision-fusion jumps) — exactly the class of bug that surfaces at
a competition, not in the sim.

Bundled here (same file, same concept): `enu_setpoint_to_px4_ned` has a
`z_ekf_adjust_ned` parameter that production never passes — it is redundant
with the adjustment already baked into `setpoint_origin_ned`. Remove it so the
API stops advertising compensation it doesn't deliver.

## Current state

`src/core/ros_px4_template_core/lib/px4_local_frame.py` (whole file is 74 lines; read it):

```python
# :46-52  observe() — deltas ARE accumulated
if self._xy_reset_counter >= 0 and xy_reset_counter != self._xy_reset_counter:
    self.x_adjust_ned += float(delta_x)
    self.y_adjust_ned += float(delta_y)
self._xy_reset_counter = int(xy_reset_counter)
if self._z_reset_counter >= 0 and z_reset_counter != self._z_reset_counter:
    self.z_adjust_ned += float(delta_z)

# :63-65  read path — deltas NOT applied (the bug)
local_x = x_ned - (self.home_x_ned or 0.0)
local_y = y_ned - (self.home_y_ned or 0.0)
return ned_to_enu(local_x, local_y, local_z)

# :67-73  write path — deltas ARE applied
@property
def setpoint_origin_ned(self) -> tuple[float, float, float]:
    return (
        (self.home_x_ned or 0.0) + self.x_adjust_ned,
        ...
```

`local_z` comes from `px4_local_z_ned(z_ned, z_global=..., origin_z_ned=self.home_z_ned)`
(`frames.py:74-89`) — also without the z adjust.

Semantics check (why subtracting is correct): after a reset, PX4 reports
`x_ned_new = x_ned_old + delta` for the same physical point. To keep the
anchored ENU pose continuous, the read path must subtract the accumulated
adjustment: `local_x = x_ned - home_x - x_adjust_ned`. The write path
correctly maps an anchored target back into the shifted PX4 frame by ADDING
the adjust to the origin (`setpoint_origin_ned`), consumed by
`offboard_controller._publish_position_setpoint`
(`offboard_controller.py:426-433`) via `/drone/local_origin`.

Existing tests to build on: `tests/unit/test_px4_local_frame.py` —
`test_px4_local_frame_anchors_xyz_read` (no-reset path; must stay green
unchanged) and `test_px4_local_frame_accumulates_ekf_reset_into_setpoint_origin`
(write path). Note the second test's `observe(0.5, -0.5, -2972.25, ...,
delta_x=0.5, delta_y=-0.5, delta_z=0.25)`: with the fix, that call must return
ENU `(0.0, 0.0, 0.0)` (continuous pose across the reset) instead of today's
jumped value.

The dead parameter: `frames.py:92-114`:

```python
def enu_setpoint_to_px4_ned(..., z_ekf_adjust_ned: float = 0.0) -> ...:
    ...
    z_ned = origin_z_ned + z_local + z_ekf_adjust_ned
```

Sole production caller `offboard_controller.py:428` never passes it; only
`tests/unit/test_frames.py` exercises the non-zero path. Because
`setpoint_origin_ned` already carries `z_adjust_ned`, passing BOTH would
double-apply — remove the parameter.

## Commands you will need

| Purpose | Command | Expected |
|---------|---------|----------|
| Quality gate | `just check` | exit 0 |
| Targeted tests | `uv run pytest tests/unit/test_px4_local_frame.py tests/unit/test_frames.py -q` | all pass |
| Live regression | `just scenario 01_arm_takeoff` | PASS |

## Scope

**In scope**:
- `src/core/ros_px4_template_core/lib/px4_local_frame.py`
- `src/core/ros_px4_template_core/lib/frames.py` (remove `z_ekf_adjust_ned`)
- `tests/unit/test_px4_local_frame.py`, `tests/unit/test_frames.py`

**Out of scope**:
- `position_node.py` / `offboard_controller.py` — no call-site changes needed
  (verify: `grep -rn "z_ekf_adjust_ned" src/` must show only frames.py + tests
  before you start)
- `setpoint_origin_ned` — its semantics are correct; do not "symmetrize" it

## Git workflow

- Branch: `advisor/051-ekf-reset-read-path`
- Commit style: `fix(frames): apply EKF-reset deltas to the anchored read path`

## Steps

### Step 1: Characterization first — pin the no-reset path

Add a test to `test_px4_local_frame.py` that replays a longer no-reset
sequence (3+ observes with varying positions, counters constant) and asserts
the exact ENU outputs of today's code. Run it against UNMODIFIED code.

**Verify**: `uv run pytest tests/unit/test_px4_local_frame.py -q` → all pass.

### Step 2: Fix the read path

In `observe()`:

```python
local_x = x_ned - (self.home_x_ned or 0.0) - self.x_adjust_ned
local_y = y_ned - (self.home_y_ned or 0.0) - self.y_adjust_ned
```

For z: subtract `self.z_adjust_ned` from `local_z` after the
`px4_local_z_ned` call (only when an origin is latched — mirror the existing
`home_z_ned is None` first-sample handling; on the very first sample all
adjusts are 0.0 so no special case is actually reachable, but keep the order:
accumulate-deltas → compute-local → subtract-adjust).

Update the module docstring (`px4_local_frame.py:1-5`): the read path now
reads "PX4 local NED minus accumulated EKF-reset deltas -> takeoff-anchored
ENU (continuous across resets)".

### Step 3: Reset-scenario tests

Extend `test_px4_local_frame.py`:

- **Continuity across xy reset**: observe at `(1.0, 2.0, -5.0)` (anchored),
  then the same physical point re-reported after a reset as
  `(1.5, 1.5, -5.0)` with `xy_reset_counter=1, delta_x=0.5, delta_y=-0.5` →
  ENU must equal the pre-reset ENU exactly.
- **Continuity across z reset** (same shape, `delta_z`).
- **Write path unchanged**: `setpoint_origin_ned` still equals
  `home + adjust` (the existing test already asserts this; keep it green).
- **Round trip**: after a reset, a GoTo back to the current anchored pose maps
  (via `enu_setpoint_to_px4_ned` with `setpoint_origin_ned`) to the NED point
  PX4 currently reports — i.e. commanded hold = no motion. This is the
  end-to-end property the bug violated.

**Verify**: `uv run pytest tests/unit/test_px4_local_frame.py -q` → all pass
including the new ones. Note: `test_px4_local_frame_accumulates_ekf_reset_into_setpoint_origin`
asserts only the origin, so it stays valid as written.

### Step 4: Remove `z_ekf_adjust_ned`

Delete the parameter and its term from `enu_setpoint_to_px4_ned`
(`frames.py:92-114`) and the docstring sentence referencing
`adjustSetpointForEKFResets`. Update `tests/unit/test_frames.py` — delete or
rewrite the test case that passes a non-zero `z_ekf_adjust_ned` (find it:
`grep -n z_ekf_adjust_ned tests/unit/test_frames.py`).

**Verify**: `grep -rn "z_ekf_adjust_ned" .` → no matches outside `plans/`.
`just check` → exit 0.

### Step 5: Live regression

`just scenario 01_arm_takeoff` → PASS (EKF resets don't normally occur in a
clean SITL boot; this gate proves the no-reset path is unbroken in flight).

## Done criteria

- [ ] All Step 3 tests exist and pass; the Step 1 characterization test passes UNMODIFIED
- [ ] `grep -rn "z_ekf_adjust_ned"` clean outside `plans/`
- [ ] `just check` exits 0
- [ ] `just scenario 01_arm_takeoff` PASS
- [ ] `plans/README.md` row updated

## STOP conditions

- The Step 1 characterization test fails after your Step 2 change — the fix
  leaked into the no-reset path; revert and report.
- You find another consumer of `x_adjust_ned`/`y_adjust_ned`/`z_adjust_ned`
  beyond `setpoint_origin_ned` (`grep -rn "adjust_ned" src/`) — the plan's
  model of the code is incomplete.

## Maintenance notes

- Hardware bring-up (B54) is where EKF resets actually happen; when a real FC
  flies this code, watch the `xy_reset_counter` path in early flights.
- Reviewer: confirm the subtraction lands in `observe()` and NOT also in
  `setpoint_origin_ned` (double-fix = same bug, opposite sign).
