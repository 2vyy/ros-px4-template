# Plan 050: Wire the `estimate_invalid` safety guard to a real PX4 validity signal

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 01f94c7..HEAD -- src/core/ros_px4_template_core/nodes/mission_manager.py src/core/ros_px4_template_core/nodes/position_node.py src/px4_ros_msgs/ docs/TOPICS.md`
> On any mismatch with the "Current state" excerpts, STOP.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW (activates a currently-inert guard; main risk is false positives, mitigated below)
- **Depends on**: none
- **Category**: bug (safety)
- **Planned at**: commit `01f94c7`, 2026-07-10

## Why this matters

Every shipped mission wires `estimate_invalid → hold_safe` as its **first
safety edge**, but the guard can never fire: `mission_manager` hardcodes
`self._estimate_ok = True` at init and never updates it. The advertised
"bad estimate → hold safe" net is dead in all five missions. A
degraded-but-still-publishing estimate (PX4 reporting `xy_valid`/`z_valid`
false) currently just makes `position_node` silently stop publishing, and the
only protection left is `inputs_stale` (odom silence ≥ 1 s) — a slower, less
specific diversion.

## Current state

- `src/core/ros_px4_template_core/nodes/mission_manager.py:100` —
  `self._estimate_ok = True` (only write; snapshotted verbatim at `:221`,
  passed into `Inputs.estimate_ok` at `:253`).
- `src/core/ros_px4_template_core/lib/mission/guards.py:72-74`:

  ```python
  @guard("estimate_invalid")
  def estimate_invalid(inputs: Inputs, signals: dict, params: dict) -> bool:
      return not inputs.estimate_ok
  ```

- `src/core/ros_px4_template_core/nodes/position_node.py:105-107` — the only
  place PX4's validity flags are read today, and they gate silently:

  ```python
  def _position_cb(self, msg: VehicleLocalPosition) -> None:
      if not (msg.xy_valid and msg.z_valid):
          return
  ```

  `position_node` is the single source of truth for pose (docstring line 1);
  it publishes `/drone/odom` (`nav_msgs/Odometry`) and `/drone/local_origin`.
- `config/missions/*.yaml` — 5 of 6 missions (all but `hover.yaml`) have
  `{guard: estimate_invalid, to: hold_safe}` in their `safety:` list.
- `nav_msgs/Odometry` has no boolean validity field, and its
  `pose.covariance` is currently left zeroed by `position_node`.

### Design decision (already made — implement, don't re-litigate)

Publish the validity bit from `position_node` (the node that sees the PX4
flags) using the Odometry message it already publishes: set
`odom.pose.covariance[0]` to `-1.0` when invalid is NOT an option (we simply
stop publishing today) — instead, **publish the odom message on every PX4
sample, valid or not**, and carry validity in `pose.covariance[0]`:
`0.0` = valid (current default), `-1.0` = invalid. ROS convention treats
covariance `-1` on the diagonal as "unknown/invalid", so this stays
standards-friendly, adds no new topic, no new message, and no QoS surface.
`mission_manager._odom_cb` reads it. When invalid, `position_node` keeps the
LAST valid pose values in the message (so downstream consumers don't see
zeros) but flags it.

This deliberately keeps `docs/TOPICS.md` unchanged (same topics, same types).

## Commands you will need

| Purpose | Command | Expected |
|---------|---------|----------|
| Quality gate | `just check` | exit 0 |
| Unit tests only | `uv run pytest tests/unit/ -q` | all pass |
| Live regression (operator/distrobox) | `just scenario 01_arm_takeoff` | PASS |

## Scope

**In scope**:
- `src/core/ros_px4_template_core/nodes/position_node.py`
- `src/core/ros_px4_template_core/nodes/mission_manager.py`
- `tests/unit/test_mission_guards.py` (extend) and a new
  `tests/unit/test_estimate_validity.py` if you extract a pure helper
- Node docstring "ROS 2 Interface" blocks in both nodes (document the
  covariance[0] convention)

**Out of scope**:
- `lib/mission/guards.py` — the guard itself is correct; only its input is dead
- `docs/TOPICS.md` — topics/types unchanged
- `offboard_controller.py` — it consumes `/drone/odom` for position only;
  covariance is ignored there and must stay ignored (a stale-estimate hold is
  the MISSION's job via `hold_safe`, not the controller's)
- Any new ROS message in `src/px4_ros_msgs/`

## Git workflow

- Branch: `advisor/050-wire-estimate-invalid`
- Commit style: `fix(safety): publish estimate validity so estimate_invalid can fire`

## Steps

### Step 1: `position_node` publishes validity instead of silently gating

In `_position_cb`, replace the early return with:

```python
valid = bool(msg.xy_valid and msg.z_valid)
if not valid and not self._frame.ready:
    return  # never anchored yet; nothing meaningful to publish
```

When `valid`, proceed exactly as today. When not valid (but anchored), skip
`self._frame.observe(...)` (do not corrupt the anchor with invalid samples),
reuse the last published ENU pose (store it on self), and publish the odom
with `odom.pose.covariance[0] = -1.0`. When valid, set `covariance[0] = 0.0`
explicitly. Log the invalid→valid and valid→invalid edges once each via
`self.slog.event(...)` (edge-triggered, not per-message — match the pattern in
`offboard_controller._target_pose_cb`, `offboard_controller.py:207-221`).

Update the module docstring's Interface block: note
`pose.covariance[0]: 0.0 valid / -1.0 PX4 estimate invalid`.

**Verify**: `just check` → exit 0.

### Step 2: `mission_manager` consumes it

In `_odom_cb` (`mission_manager.py:164-174`), read
`estimate_ok = msg.pose.covariance[0] >= 0.0` and store it under the lock as
`self._estimate_ok` (replacing the constant at line 100 — keep the attribute,
initialize to `True`). The snapshot code at `:221`/`:253` already forwards it.

Update the mission_manager docstring Interface block the same way.

**Verify**: `just check` → exit 0.

### Step 3: Unit tests

`tests/unit/test_mission_guards.py` already covers the guard itself. Add tests
for the new seam:

- If you extracted a pure helper (recommended:
  `estimate_ok_from_covariance(c0: float) -> bool` in
  `src/core/ros_px4_template_core/lib/frames.py` is NOT the right home — put
  it inline; it's one comparison, a helper is overkill). Instead test at the
  behavior level: extend `tests/unit/test_mission_engine.py`-style mission
  ticks are already covered; what's missing is nothing new — the REQUIRED new
  test is for `position_node`'s edge logic **if** you extract it. If the edge
  logic stays inline in the node (acceptable, matches repo style), the test
  burden is covered by the live check in Step 4.

**Verify**: `uv run pytest tests/unit/ -q` → all pass, no fewer tests than before.

### Step 4: Live verification (operator sign-off)

- `just sim --overlay auto_arm` → READY; let it take off.
- `rg "covariance" logs/latest.log` is not expected to show anything (logfmt
  only carries slog events) — instead check the healthy path:
  `just scenario 01_arm_takeoff` → PASS (estimate valid throughout, no
  spurious `hold_safe` diversion: `rg "to=hold_safe" logs/latest.log` → no match).
- Forcing a real invalid estimate in SITL is not practical in this plan;
  the invalid path is exercised by the ROS-free logic being one comparison.

**Verify**: scenario PASS line printed; no `hold_safe` transition in the log.

## Done criteria

- [ ] `grep -n "_estimate_ok = True" src/core/ros_px4_template_core/nodes/mission_manager.py` shows only the `__init__` default, and `grep -n "_estimate_ok =" ...` shows a second write in `_odom_cb`
- [ ] `position_node.py` has no bare `return` on invalid-after-anchor; covariance[0] convention documented in both node docstrings
- [ ] `just check` exits 0
- [ ] `just scenario 01_arm_takeoff` PASS with zero `to=hold_safe` transitions
- [ ] `plans/README.md` row updated

## STOP conditions

- The covariance field is already used for something else (grep
  `covariance` under `src/` first — as of `01f94c7` it is only ever zeroed).
- Scenario 01 diverts to `hold_safe` during a normal flight (false positive:
  PX4 flags flapping at boot). Report the log excerpt; the likely fix
  (debounce N samples) is a design tweak the owner should size.

## Maintenance notes

- Plan 057 (mission_manager snapshot characterization tests) will lock this
  behavior in; land 050 first so 057 tests the real semantics.
- If a future hardware bring-up (B54) adds a non-PX4 position source, that
  source must set the same covariance[0] convention.
- Reviewer: check the invalid-sample path does NOT call `frame.observe` (it
  would corrupt the EKF-reset bookkeeping with garbage samples).
