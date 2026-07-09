# Plan 040: Rename the miscounted "setpoints_sent" gate to what it counts; delete a dead quaternion write

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report - do not improvise. When done, update the status row for this plan
> in `plans/README.md` - unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat ead4cc6..HEAD -- src/core/ros_px4_template_core/lib/offboard_fsm.py src/core/ros_px4_template_core/nodes/offboard_controller.py src/core/ros_px4_template_core/nodes/position_node.py tests/unit/test_offboard_fsm.py`
> If any changed, compare the "Current state" excerpts before proceeding; on
> a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P3
- **Effort**: S
- **Risk**: LOW (rename + dead-code delete; zero logic change)
- **Depends on**: none (plan 042 touches `offboard_controller.py` later; land this first to avoid churn)
- **Category**: tech-debt
- **Planned at**: commit `ead4cc6`, 2026-07-06

## Why this matters

The arming FSM's readiness gate reads `inputs.setpoints_sent > 5`
(`lib/offboard_fsm.py:57`), but the counter it receives is incremented once
per control tick INCLUDING the early-return path that publishes only an
`OffboardControlMode` heartbeat and no trajectory setpoint
(`offboard_controller.py:290`), and trajectory setpoints are deliberately NOT
published before OFFBOARD mode (PX4/PX4-Autopilot#25273, comment at
`offboard_controller.py:297-298`). So the name lies: the gate counts control
heartbeats, not setpoints. The next person who "fixes" the counter to count
real `TrajectorySetpoint` publishes would deadlock the FSM in PREARM forever
(setpoints only flow once OFFBOARD is active, which the gate itself guards).
Renaming to the true semantics removes that trap. Bundled: a dead quaternion
write in `position_node.py` that pattern-matches as a bug on every read.

## Current state

- `lib/offboard_fsm.py:28` - `setpoints_sent: int` field of frozen
  `FsmInputs`; used once at line 57: `and inputs.setpoints_sent > 5`.
- `nodes/offboard_controller.py`:
  - line 81: `self._setpoints_sent = 0`
  - line 246: `setpoints_sent=self._setpoints_sent,` (FsmInputs kwarg)
  - lines 290 and 300: `self._setpoints_sent += 1` - BOTH tick paths (the
    have-no-odom early return and the main path). Both increments stay.
- `tests/unit/test_offboard_fsm.py:17` - `setpoints_sent=10` in the `_READY`
  baseline dict.
- `nodes/position_node.py:147`:

```python
        odom.pose.pose.orientation.z = math.sin(yaw_enu / 2.0)
        qw, qx, qy, qz = enu_quaternion_from_yaw(yaw_enu)
        odom.pose.pose.orientation.w = qw
        odom.pose.pose.orientation.x = qx
        odom.pose.pose.orientation.y = qy
        odom.pose.pose.orientation.z = qz
```

  Line 147 is dead: line 152 overwrites `orientation.z` with the identical
  value from `enu_quaternion_from_yaw` (`frames.py:59-61` returns
  `sin(yaw/2)` as its z). `math` remains used at `position_node.py:125`
  (`math.dist`), so the import stays.

Verified non-issue, do NOT touch: the `ros_time_us > 0` guard at
`offboard_controller.py:179` looks vacuous but is load-bearing in sim -
`sim_full.launch.py:225` sets `use_sim_time: true`, so the ROS clock reads 0
until the first `/clock` message and the guard stops `_xrce_connect_time`
from latching at t=0.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| FSM tests | `uv run pytest tests/unit/test_offboard_fsm.py -q` | all pass |
| No stragglers | `rg -n "setpoints_sent" src/ tests/` | no matches after rename |
| Full gate | `just check` | exit 0 |

## Scope

**In scope**:
- `src/core/ros_px4_template_core/lib/offboard_fsm.py` (field rename)
- `src/core/ros_px4_template_core/nodes/offboard_controller.py` (attr + kwarg rename)
- `tests/unit/test_offboard_fsm.py` (kwarg rename)
- `src/core/ros_px4_template_core/nodes/position_node.py` (delete line 147)

**Out of scope**:
- ANY change to what is counted, where increments happen, or the `> 5`
  threshold - this is a rename, not a behavior fix.
- The `ros_time_us > 0` guard (see above - load-bearing under sim time).
- Docstrings elsewhere that describe setpoint streaming generally.

## Git workflow

- Branch: `advisor/040-heartbeat-rename`
- Commit style: `refactor(offboard): rename setpoints_sent to offboard_heartbeats_sent; drop dead quat write`
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Rename across the three FSM files

New name: `offboard_heartbeats_sent` (it counts `OffboardControlMode`
publishes, one per control tick).

1. `lib/offboard_fsm.py`: field at line 28 and the use at line 57.
   Add one line to the field's vicinity or the module docstring stating the
   semantics, e.g. in the docstring's sequence note: "``offboard_heartbeats_sent``
   counts OffboardControlMode publishes (one per control tick); trajectory
   setpoints intentionally do not flow before OFFBOARD (PX4-Autopilot#25273),
   so do not change this to count TrajectorySetpoint or PREARM never clears."
2. `nodes/offboard_controller.py`: rename `self._setpoints_sent` (lines 81,
   290, 300) to `self._offboard_heartbeats_sent` and the kwarg at line 246 to
   `offboard_heartbeats_sent=self._offboard_heartbeats_sent`.
3. `tests/unit/test_offboard_fsm.py`: `setpoints_sent=10` ->
   `offboard_heartbeats_sent=10`.

**Verify**: `rg -n "setpoints_sent" src/ tests/ tools/` -> no matches;
`uv run pytest tests/unit/test_offboard_fsm.py -q` -> all pass

### Step 2: Delete the dead write in `position_node.py`

Remove line 147 (`odom.pose.pose.orientation.z = math.sin(yaw_enu / 2.0)`)
only. The `enu_quaternion_from_yaw` block below it stays byte-identical.

**Verify**: `rg -n "math\." src/core/ros_px4_template_core/nodes/position_node.py`
-> still shows `math.dist` (import remains justified);
`rg -c "orientation.z" src/core/ros_px4_template_core/nodes/position_node.py` -> 1

### Step 3: Full gate

**Verify**: `just check` -> exit 0 (build + unit tests confirm the rename is
complete; a missed site would fail at import or FsmInputs construction).

## Test plan

No new tests: the existing `test_offboard_fsm.py` suite exercises the renamed
field in every test via the `_READY` dict, and `just check` builds the
workspace, catching any missed rename site. Behavior is provably identical
(rename + dead-store delete only).

## Done criteria

- [ ] `rg -n "setpoints_sent" src/ tests/ tools/` -> no matches
- [ ] `rg -n "offboard_heartbeats_sent" src/core/ros_px4_template_core/lib/offboard_fsm.py src/core/ros_px4_template_core/nodes/offboard_controller.py tests/unit/test_offboard_fsm.py` -> matches in all three
- [ ] `position_node.py` has exactly one `orientation.z` assignment
- [ ] `uv run pytest tests/unit/test_offboard_fsm.py -q` all pass
- [ ] `just check` exits 0
- [ ] `git status` shows only the four in-scope files modified
- [ ] `plans/README.md` status row updated

## STOP conditions

- Any occurrence of `setpoints_sent` outside the four files (an unknown
  consumer - report it; scenarios/tools were checked clean at `ead4cc6`).
- Anything tempts you to change an increment site or the `> 5` threshold -
  that is a behavior change; out of scope, report instead.

## Maintenance notes

- Reviewer: the diff must contain zero logic edits - identifier lines and the
  one deleted dead store only, plus the docstring sentence in
  `offboard_fsm.py`.
- Plan 042 (precision landing) edits `offboard_controller.py` next; merging
  this rename first keeps that diff clean.
