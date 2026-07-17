# Plan 057: Characterization tests for the offboard safety latches and the mission_manager snapshot

> **Executor instructions**: Follow this plan step by step, verifying each
> step. On any STOP condition, stop and report. When done, update
> `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 01f94c7..HEAD -- src/core/ros_px4_template_core/nodes/offboard_controller.py src/core/ros_px4_template_core/nodes/mission_manager.py tests/unit/`
> On any mismatch with the excerpts below, STOP. If plan 050 landed first,
> `mission_manager._odom_cb` also writes `_estimate_ok` — include that in the
> snapshot tests instead of treating it as drift.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: LOW (additive tests; a small mechanical extraction of pure logic)
- **Depends on**: none (but reconcile with 050 as noted above; land after 050 if possible)
- **Category**: tests
- **Planned at**: commit `01f94c7`, 2026-07-10

## Why this matters

The three safety latches in `offboard_controller` (disarm latch plan 030,
landing latch plan 042, failsafe latch plan 044) are the mechanism that stops
this node from fighting PX4's own failsafe/lander — and the edge-detection
that SETS them, plus the param-callback that guards CLEARING them, has zero
unit coverage (`grep -rn "OffboardController" tests/` → nothing). Same for
`mission_manager._snapshot`, the raw-ROS→`Inputs` seam where staleness
windows, the `z_eff` altitude fusion, and stability-reset logic live: the
engine's guarantees are tested only *given* a well-formed `Inputs`; the code
that builds it ships green through `just check` untested. These are the two
highest-churn safety files in the repo (plans 030/041/042/044 all touched
them). A regression latching on the wrong edge would only surface in a live
sim — or a competition.

## Current state

The logic to cover, all in plain methods taking plain message objects:

- `offboard_controller.py:263-283` `_status_cb` — armed→disarmed edge sets
  `_disarm_latched`; failsafe rising edge sets `_failsafe_latched`; falling
  edge logs but does NOT clear the latch; `_px4_ever_disarmed` set once when
  disarmed with `pre_flight_checks_pass`.
- `offboard_controller.py:285-294` `_land_cb` — idempotent (`if self._landing:
  return`); sets `_landing`/`_landing_latched` BEFORE commanding NAV_LAND.
- `offboard_controller.py:296-325` `_command_ack_cb` — NAV_LAND ack accepted/
  denied logging; ARM_DISARM ack: UNSUPPORTED/FAILED promotes terminal
  `_arm_failed` (once).
- `offboard_controller.py:128-153` `_on_set_params` — `auto_arm=true` is
  REJECTED while `_failsafe_active` or while `(_landing and _armed)`;
  otherwise clears whichever of the three latches are set (landing clear also
  clears `_landing`).
- `mission_manager.py:211-265` `_snapshot` — under `_state_lock`: marker
  staleness (`now - marker_time > 1.0` zeroes stability persistently),
  detection tuple built only when fresh (≤1.0 s), stability dict only when
  ≤`_STABLE_FRESH_S` (0.3 s, `:65`), `z_eff = max(pos_enu[2], ctrl_alt)`,
  `altitude_ok = z_eff >= takeoff_alt - tol`, `input_ages` for
  odom/battery/vehicle_status (`inf` when never seen).
- Feeders: `_detection_cb:176-191` (invalid msg clears offset + stability;
  valid increments stability), `_battery_cb:193-201`,
  `_vehicle_status_cb:203-209`.

Both classes are `rclpy` Nodes, so tests need `rclpy.init()`. Precedent for
node-level unit tests in this repo: there is none — every current unit test is
rclpy-free, and `tests/unit/test_scenario_verdict.py` has a KNOWN rclpy
collection error in some environments (mentioned in `plans/README.md` plan 016
notes). Therefore: **prefer extraction over instantiation.**

Extraction pattern to follow: `lib/offboard_fsm.py` — a pure
`tick(FsmInputs) -> FsmResult` extracted from this very node, tested in
`test_offboard_fsm.py`. Do the same shape.

## Commands you will need

| Purpose | Command | Expected |
|---------|---------|----------|
| Quality gate | `just check` | exit 0 |
| Targeted | `uv run pytest tests/unit/test_offboard_latches.py tests/unit/test_mission_inputs.py -q` | all pass |
| Live regression | `just scenario 08_precision_land` | PASS (exercises all three latches) |

## Scope

**In scope**:
- `src/core/ros_px4_template_core/lib/offboard_latches.py` (new, pure)
- `src/core/ros_px4_template_core/lib/mission_inputs.py` (new, pure) — or a
  function inside `lib/mission/` if that reads better; NOT inside
  `mission_manager.py`
- `nodes/offboard_controller.py`, `nodes/mission_manager.py` (thin rewiring only)
- `tests/unit/test_offboard_latches.py`, `tests/unit/test_mission_inputs.py` (new)

**Out of scope**:
- ANY behavior change. This is characterization: the pure functions must
  reproduce today's semantics exactly, including the quirks (falling failsafe
  edge does not clear the latch; `marker_stability` is zeroed persistently on
  staleness). If you believe a semantic is wrong, STOP and report — do not fix.
- `lib/offboard_fsm.py` (already pure + tested)
- The `_STABLE_FRESH_S`/1.0-literal naming cleanup — that is plan 061's job;
  here just reference the same values

## Git workflow

- Branch: `advisor/057-latch-snapshot-tests`
- Commit style: `test(safety): extract + characterize offboard latches and mission input snapshot`

## Steps

### Step 1: Extract latch transitions

New `lib/offboard_latches.py`: a small dataclass + pure transition functions,
e.g.

```python
@dataclass
class Latches:
    armed: bool = False
    disarm_latched: bool = False
    failsafe_active: bool = False
    failsafe_latched: bool = False
    landing: bool = False
    landing_latched: bool = False
    arm_failed: bool = False
    arm_fail_reason: str = ""
    px4_ever_disarmed: bool = False

def on_vehicle_status(l: Latches, *, armed: bool, failsafe: bool,
                      disarmed_state: bool, preflight_ok: bool) -> list[str]:
    """Mutate latches per today's _status_cb; return event names to log."""

def on_land_command(l: Latches) -> bool:  # returns "send NAV_LAND now?"
def on_arm_ack(l: Latches, result: int) -> list[str]:
def try_clear_auto_arm(l: Latches) -> tuple[bool, str, list[str]]:  # (ok, reject_reason, events)
```

Port the bodies from the node verbatim (event names from `lib/events.py`).
Rewire the node callbacks to delegate: each callback becomes "unpack msg →
call pure fn → publish/slog per returned events". The node keeps its
attribute names by mirroring from the `Latches` instance OR by replacing the
attributes with the dataclass — choose the smaller diff (mirroring the
dataclass as `self._latches` and updating the ~10 read sites is acceptable;
`_update_state_machine:333-338` reads three of them).

**Verify**: `just check` → exit 0 (build + all existing tests green).

### Step 2: Latch tests (`tests/unit/test_offboard_latches.py`)

Model on `test_offboard_fsm.py`'s style. Cover at minimum:

- armed→disarmed edge latches `disarm_latched`; disarmed→disarmed does not re-fire the event
- failsafe rising edge latches; falling edge emits the "cleared live" event but latch STAYS set
- `try_clear_auto_arm` while `failsafe_active` → rejected with the failsafe reason
- `try_clear_auto_arm` while `landing and armed` → rejected with the landing reason
- `try_clear_auto_arm` after touchdown (`landing`, not armed) → clears landing latch AND `landing`
- clear with all three latched (no active failsafe/landing) → all cleared, three events
- `on_arm_ack` UNSUPPORTED/FAILED → `arm_failed` once (second ack doesn't duplicate); DENIED/TEMPORARILY_REJECTED → not terminal
- `on_land_command` idempotency: first call True, second False
- `px4_ever_disarmed` requires `preflight_ok`

### Step 3: Extract the snapshot math

New pure function (suggested home `lib/mission_inputs.py`):

```python
def build_inputs(now: float, s: MissionManagerState, *, takeoff_alt: float,
                 takeoff_alt_tol: float, stable_fresh_s: float = 0.3) -> tuple[Inputs, int]:
    """Pure _snapshot body over a plain-field state snapshot.
    Returns (inputs, new_marker_stability) — the caller persists the zeroed
    stability under its lock, preserving today's persistent-reset semantics."""
```

where `MissionManagerState` is a small dataclass mirroring the locked fields
(`pos_enu, yaw_enu, have_odom, odom_time, armed, ctrl_alt, estimate_ok,
marker_offset_body, marker_id_seen, marker_time, marker_stability,
battery_remaining, have_battery, battery_time, failsafe_active,
have_vehicle_status, vehicle_status_time`). `mission_manager._snapshot`
becomes: copy fields under the lock → call `build_inputs` → write back the
returned stability under the lock. Byte-for-byte semantics.

**Verify**: `just check` → exit 0.

### Step 4: Snapshot tests (`tests/unit/test_mission_inputs.py`)

Table-test the boundaries:

- fresh marker (age 0.2 s): detection present AND stability dict present
- marker age 0.5 s (fresh window but > `_STABLE_FRESH_S`): detection present, stability EMPTY
- marker age 1.5 s: no detection, stability reset returned as 0
- marker age exactly 1.0 / exactly 0.3: pin today's `>` / `<=` boundaries
- `z_eff`: pose z 1.0 + ctrl_alt 2.9 (takeoff 3.0, tol 0.3) → z_eff 2.9, `altitude_ok` True; both low → False
- `input_ages`: never-seen battery → `inf`; seen → `now - t`
- `battery_remaining=None` passes through as None

### Step 5: Live regression

`just scenario 08_precision_land` → PASS (this scenario exercises land latch +
disarm latch + the marker freshness windows end to end);
`just scenario 01_arm_takeoff` → PASS.

## Done criteria

- [ ] `grep -c "def test_" tests/unit/test_offboard_latches.py` ≥ 9; `tests/unit/test_mission_inputs.py` ≥ 7; all pass
- [ ] `nodes/offboard_controller.py` and `nodes/mission_manager.py` contain no latch/snapshot decision logic beyond delegation (reviewer judgment; the pure modules own it)
- [ ] `just check` exit 0
- [ ] `just scenario 08_precision_land` and `01_arm_takeoff` PASS (operator)
- [ ] `plans/README.md` row updated

## STOP conditions

- Porting reveals a semantic you believe is a bug (e.g. the falling-failsafe
  edge, the persistent stability zeroing) — characterize it AS IS and list it
  in your report; do not fix within this plan.
- The rewiring diff in either node exceeds ~60 lines — you are refactoring,
  not extracting; back up and take the smaller mirror approach.
- Plan 050's `_estimate_ok` write conflicts with your state dataclass —
  reconcile (include the field), don't drop it.

## Maintenance notes

- Future latch changes (e.g. a fourth latch for geofence) now have a test
  home and a pure seam; PRs touching `offboard_controller` safety logic
  should be rejected if they bypass `lib/offboard_latches.py`.
- Plan 061 (QoS/constants cleanup) touches the same files trivially — land in
  either order, expect a 2-line merge.
