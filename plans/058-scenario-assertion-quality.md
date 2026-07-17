# Plan 058: Scenario assertions verify the flight, not the reporter (03 motion check, arm-trigger detail, auto-arm opt-out)

> **Executor instructions**: Follow this plan step by step, verifying each
> step. On any STOP condition, stop and report. When done, update
> `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 01f94c7..HEAD -- tests/scenarios/ tools/scenario_scaffold.py`
> On any mismatch with the excerpts below, STOP.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW (test-side only; no runtime node changes)
- **Depends on**: none
- **Category**: tests
- **Planned at**: commit `01f94c7`, 2026-07-10

## Why this matters

Three quality gaps in the live-scenario harness reduce what a green e2e run
actually proves:

1. **Scenario 03 tests the reporter, not the flight.** It passes when
   `mission_status.waypoint_index >= 3` — a value `mission_manager` computes
   from its own reach logic over `/drone/odom`. A mission-engine bug that
   advances the index without the airframe traversing the path passes
   undetected. Scenario 02 already shows the right pattern: subscribe to
   PX4's own `/fmu/out/vehicle_local_position_v1` and assert independently.
2. **`trigger_auto_arm()`'s result is discarded** by the `Scenario` base
   class, so when a scenario times out the failure detail cannot distinguish
   "the arm param-set silently failed" (harness/environment problem) from
   "the vehicle didn't fly" (product problem) — for 6 of 7 scenarios.
3. **The base class force-arms unconditionally**, even for scenarios whose
   declared overlay intends a passive posture. Today all seven scenarios want
   arming, so this is a latent trap for the next passive scenario (e.g. a
   pure-perception check), not an active bug — fix it as an opt-out attribute
   while we're in the file.

## Current state

- `tests/scenarios/_common.py:156-159`:

  ```python
  async def run(self) -> bool:
      rclpy.init()
      trigger_auto_arm()
      started = time.monotonic()
  ```

  and the timeout path `:166-169` writes
  `{"reason": "timeout", **self.report_detail()}` — no arm-trigger status.
  `trigger_auto_arm` (`:48-53`) already returns a bool and WARNs on failure.

- `tests/scenarios/03_waypoint.py` (54 lines, read it) — subscribes only to
  `/drone/mission_status`; `done()` is
  `self._node.waypoint_index >= _WAYPOINT_COUNT or self._node.phase == "done"`;
  `_WAYPOINT_COUNT = 3` matches `config/paths/demo.yaml`
  (`{0,0,3}, {5,0,3}, {8,0,3}`).

- The independent-motion pattern to copy: `tests/scenarios/02_hover_hold.py`
  subscribes to `/fmu/out/vehicle_local_position_v1` with `PX4_QOS` from
  `_common.py:19-24` and converts NED→ENU inline. Note PX4 local position is
  NED: ENU x = msg.y − origin, ENU y = msg.x − origin, alt = −msg.z (read 02's
  handling and mirror it exactly, including its takeoff-origin capture).

- The waypoints in `config/paths/demo.yaml` are anchored-ENU; PX4's local
  frame origin coincides with the takeoff point in SITL (02 already relies on
  this, capturing the first sample as origin).

## Commands you will need

| Purpose | Command | Expected |
|---------|---------|----------|
| Quality gate | `just check` | exit 0 |
| Scenario imports test | `uv run pytest tests/unit/test_scenario_imports.py tests/unit/test_scenario_verdict.py -q` | pass |
| Live (operator/distrobox) | `just scenario 03_waypoint` | PASS with per-waypoint detail |
| Full | `just test e2e` | all PASS |

## Scope

**In scope**:
- `tests/scenarios/_common.py` (capture arm result; `auto_arm` class attribute)
- `tests/scenarios/03_waypoint.py` (independent motion assertion)

**Out of scope**:
- The other six scenarios (02 already independent; 01/05/06/07/08 have their
  own domain assertions — widening them is not this plan)
- `tools/scenario_scaffold.py` template — leave the stub minimal
- Runtime nodes and `mission_manager.waypoint_index` semantics

## Git workflow

- Branch: `advisor/058-scenario-assertions`
- Commit style: `test(scenario): 03 asserts vehicle motion; base class reports arm trigger`

## Steps

### Step 1: Base class captures the arm trigger + opt-out

In `Scenario`:

```python
auto_arm: bool = True          # class attribute, opt out for passive scenarios

async def run(self) -> bool:
    rclpy.init()
    self._arm_trigger_ok: bool | None = self.auto_arm and trigger_auto_arm() or (None if not self.auto_arm else False)
```

(Write it readably — the intent: `None` when auto_arm is False, else the bool
result. The one-liner above is illustrative, not house style.)

Merge `{"arm_trigger_ok": self._arm_trigger_ok}` into the detail dict on ALL
exit paths (timeout, fail_reason, pass, exception) — timeout at `:166-169`,
fail at `:172-175`, pass at `:176`, exception at `:178-185`. Also skip
`trigger_cleanup()`'s param-set half when `auto_arm` is False (read
`trigger_cleanup` `:56-69`; the land command half stays unconditional — a
passive scenario that never armed lands harmlessly).

**Verify**: `just check` → exit 0 (scenario files are import-tested by
`tests/unit/test_scenario_imports.py`).

### Step 2: Scenario 03 asserts independent motion

Extend `03_waypoint.py`'s `_Node` with a `/fmu/out/vehicle_local_position_v1`
subscription (import `PX4_QOS` from `_common`, `VehicleLocalPosition` from
`px4_msgs.msg` — mirror 02's imports and origin capture). Track, per declared
waypoint, the minimum distance the vehicle achieved to it in ENU:

```python
_WAYPOINTS_ENU = [(0.0, 0.0, 3.0), (5.0, 0.0, 3.0), (8.0, 0.0, 3.0)]  # config/paths/demo.yaml
_REACH_TOL_M = 0.8   # mission tolerance 0.4 + estimator/discretization margin
```

`done()` stays `waypoint_index >= 3 or phase == "done"`, but add
`fail_reason()`: after `done()`, if any waypoint's `min_dist > _REACH_TOL_M`,
return `f"index advanced but vehicle missed wp{i} (min {min_dist:.2f}m)"`.
`report_detail()` gains `wp_min_dists=[round(d, 2), ...]`.

Keep the tolerance honest: the mission dwells 2 s within 0.4 m of each
waypoint, so `min_dist` should be well under 0.8 m in a healthy run; the
margin absorbs estimator noise, not misses.

**Verify**: `uv run pytest tests/unit/test_scenario_imports.py -q` → pass
(file still imports).

### Step 3: Live verification (operator/distrobox)

- `just scenario 03_waypoint` → `PASS 03_waypoint ... wp_min_dists=[...]` with
  all values < 0.8.
- Confirm the failure detail plumbing: `rg arm_trigger_ok logs/scenario_03_waypoint.json`
  → present and `true`.
- `just test e2e` → all 7 PASS (no regression; 03's added subscription must
  not slow it past its 300 s timeout).

## Test plan

Live gates above; plus the import-level unit tests already in place. No new
pytest files — the scenario harness is live-verified by design (see
`_common.py:1` docstring "not pytest").

## Done criteria

- [ ] Every `write_report` exit path includes `arm_trigger_ok` (grep the file: 4 call sites)
- [ ] `Scenario.auto_arm` exists, default True; cleanup respects it
- [ ] 03 has the PX4-position subscription, per-waypoint `min_dist` tracking, and the `fail_reason` check
- [ ] `just check` exit 0; `just scenario 03_waypoint` PASS with `wp_min_dists` in detail; `just test e2e` all PASS
- [ ] `plans/README.md` row updated

## STOP conditions

- 03 PASSes on index but the motion check reports a miss on a healthy-looking
  flight (tolerance mis-set or frame conversion wrong) — compare the recorded
  `wp_min_dists` against `rg waypoint logs/latest.log`; if the ENU conversion
  in your subscription disagrees with 02's, fix that; if the vehicle GENUINELY
  misses waypoints while the index advances, you found the exact bug this
  plan guards against — report it, do not loosen the tolerance past 0.8 m.
- `_common.py`'s exit paths have been restructured (drift) — reconcile.

## Maintenance notes

- New scenarios should copy 03's independent-verification pattern; the
  scaffold stub deliberately stays minimal — mention the pattern in review
  when a new scenario asserts only self-reported state.
- The `auto_arm=False` path has no user yet; the first passive scenario
  (plan 062's perception check is a candidate) becomes its live test.
