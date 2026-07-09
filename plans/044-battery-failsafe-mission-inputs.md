# Plan 044: Battery and failsafe reach the mission FSM (`battery_low` / `failsafe_active` guards)

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report - do not improvise. When done, update the status row for this plan
> in `plans/README.md` - unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat ead4cc6..HEAD -- src/core/ros_px4_template_core/lib/mission/ src/core/ros_px4_template_core/nodes/mission_manager.py`
> Plans 041/042 legitimately touch `mission_manager.py` and `lib/mission/`
> first - reconcile with their diffs. Any OTHER drift is a STOP condition.

## Status

- **Priority**: P2 (direction: competition capability)
- **Effort**: M
- **Risk**: LOW-MED (new subscriptions + safety guards; defaults are fail-open so existing missions are untouched)
- **Depends on**: none hard (independent of 041/042; merge after them to avoid
  `mission_manager.py` conflicts)
- **Category**: feature
- **Planned at**: commit `ead4cc6`, 2026-07-06

## Why this matters

A competition mission that ignores battery state flies its search pattern
until PX4's failsafe yanks control away mid-task - losing both the task and
the choice of where to land. The mission FSM's safety tier exists exactly for
this ("a hazard always wins over normal progression", docs/MISSIONS.md), but
its `Inputs` snapshot carries no battery or failsafe information, so no
mission can express "return to origin at 20% battery" or "hold safe when PX4
enters failsafe". PX4 already publishes both facts on the uXRCE bridge; this
plan carries them into the snapshot and adds two guards.

## Current state

- `lib/mission/types.py:10-22` - frozen `Inputs`; the last three fields
  (`detections`, `detection_stability`, `input_ages`) have defaults, so new
  defaulted fields append cleanly at the end.
- `lib/mission/guards.py` - registry of pure predicates; pattern to copy is
  `estimate_invalid` (lines 72-74).
- `nodes/mission_manager.py`:
  - Subscribes only `/drone/controller_status`, `/drone/odom`,
    `/drone/marker_detection`, all `_RELIABLE_QOS` (lines 39-41 define the
    profile; there is NO PX4 QoS profile in this file yet).
  - `_snapshot` (lines 142-168) builds the `Inputs`.
  - `self._estimate_ok = True` is a hardcoded placeholder (line 80) - this
    plan gives it real data too (see Step 3.4).
- PX4 QoS pattern to copy (`nodes/offboard_controller.py:35-40`):
  `BEST_EFFORT` reliability, `TRANSIENT_LOCAL` durability, `KEEP_LAST`
  depth 10.
- PX4 messages (px4_msgs, branch `release/1.17`):
  - `BatteryStatus.remaining`: float32, 0.0-1.0 (fraction).
  - `VehicleStatus.failsafe`: bool.
- Topic names: versioned topics get a `_v1` suffix (docs/TOPICS.md "PX4
  versioned topics"). `vehicle_status_v1` is confirmed in use. The battery
  topic is expected at `/fmu/out/battery_status_v1` but MUST be verified live
  in Step 6 (fallback: `/fmu/out/battery_status` unversioned; if neither
  exists the uXRCE publication list does not include it - STOP condition).
- Schema: `battery_low` and `failsafe_active` are NEW guard names ->
  regenerate `schemas/mission.schema.json` (drift unit test exists).
- Docs contract: new subscription -> node docstring block + `docs/TOPICS.md`
  rows (`just log topics` validates presence of backticked topics against the
  live graph).

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Guard tests | `uv run pytest tests/unit/test_mission_guards.py -q` | all pass |
| Schema regen | `just mission schema > schemas/mission.schema.json` | drift test passes |
| Full gate | `just check` | exit 0 |
| Topic name check (operator, sim up) | `ros2 topic list \| grep -i battery` | the real name |
| Live guard check (operator) | see Step 6 | RTL-style divert observed |

## Scope

**In scope**:
- `src/core/ros_px4_template_core/lib/mission/types.py` (two appended fields)
- `src/core/ros_px4_template_core/lib/mission/guards.py` (two guards)
- `src/core/ros_px4_template_core/nodes/mission_manager.py` (two subscriptions + snapshot)
- `tests/unit/test_mission_guards.py`
- `schemas/mission.schema.json` (regenerated)
- `docs/TOPICS.md`, `docs/MISSIONS.md`

**Out of scope**:
- Changing any shipped mission YAML to USE the guards (document the pattern;
  missions opt in per competition task).
- `offboard_controller` - it has its own failsafe-adjacent logic (disarm
  latch); no changes.
- Battery estimation/filtering - raw `remaining` passes through; PX4 owns the
  estimate.
- `estimate_ok` beyond the minimal wiring in Step 3.4.

## Git workflow

- Branch: `advisor/044-battery-failsafe-inputs`
- Commit style: `feat(mission): battery_remaining and failsafe in Inputs; battery_low/failsafe_active guards`
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Extend `Inputs`

Append to the END of the `Inputs` dataclass (after `input_ages`):

```python
    battery_remaining: float = 1.0
    failsafe: bool = False
```

Fail-open defaults: with no battery data the guard never trips (1.0 full),
with no status data failsafe reads False. Existing constructors (node,
tests) keep working unchanged.

**Verify**: `uv run pytest tests/unit -q` -> no failures

### Step 2: The guards

In `lib/mission/guards.py` (bottom, matching the existing style):

```python
@guard("battery_low")
def battery_low(inputs: Inputs, signals: dict, params: dict) -> bool:
    return inputs.battery_remaining <= float(params.get("frac", 0.2))


@guard("failsafe_active")
def failsafe_active(inputs: Inputs, signals: dict, params: dict) -> bool:
    return inputs.failsafe
```

Tests in `tests/unit/test_mission_guards.py` (copy the file's Inputs-builder
pattern):

- `battery_low`: 0.5 with default frac -> False; 0.15 -> True; boundary 0.2
  -> True (`<=`); custom `frac: 0.5` with 0.4 -> True.
- `failsafe_active`: default Inputs -> False; `failsafe=True` -> True.
- Defaults regression: an `Inputs` built WITHOUT the new kwargs has
  `battery_remaining == 1.0` and `failsafe is False`.

**Verify**: `uv run pytest tests/unit/test_mission_guards.py -q` -> all pass

### Step 3: `mission_manager` subscriptions + snapshot

1. Add a PX4 QoS profile next to `_RELIABLE_QOS` (import `DurabilityPolicy`):

```python
_PX4_QOS = QoSProfile(
    reliability=ReliabilityPolicy.BEST_EFFORT,
    durability=DurabilityPolicy.TRANSIENT_LOCAL,
    history=HistoryPolicy.KEEP_LAST,
    depth=10,
)
```

2. State fields in `__init__`: `self._battery_remaining = 1.0`,
   `self._failsafe = False`.
3. Subscriptions (in `__init__`, `callback_group=self._sub_group` like the
   others; import `BatteryStatus`, `VehicleStatus` from `px4_msgs.msg`):
   - `/fmu/out/battery_status_v1` -> `_battery_cb`:
     `self._battery_remaining = float(msg.remaining)`.
   - `/fmu/out/vehicle_status_v1` -> `_vehicle_status_cb`:
     `self._failsafe = bool(msg.failsafe)`.
   Use the `_v1` names to match the file's other PX4-topic conventions; the
   live check in Step 6 confirms the battery name (STOP condition if wrong).
4. In `_vehicle_status_cb`, also wire the placeholder honestly - PX4's
   failsafe already implies a degraded vehicle, but keep `estimate_ok`
   untouched unless a field maps cleanly; if `VehicleStatus` on this branch
   has no obvious estimator-health flag, leave `self._estimate_ok` alone and
   note it in your report (do NOT invent a mapping).
5. In `_snapshot`, pass `battery_remaining=self._battery_remaining,
   failsafe=self._failsafe` to `Inputs`.
6. Update the module docstring's Subscriptions block with both topics.

**Verify**: `uv run ruff check src/core/ros_px4_template_core/nodes/mission_manager.py` -> exit 0

### Step 4: Schema + docs

1. `just mission schema > schemas/mission.schema.json`; confirm the diff adds
   only the two guard names to the guard enum.
2. `docs/TOPICS.md`: add pub row `/fmu/out/battery_status_v1`
   (`px4_msgs/msg/BatteryStatus`, pub, PX4 uXRCE-DDS bridge) and extend the
   subscriptions table: `/fmu/out/battery_status_v1` -> `mission_manager`;
   `/fmu/out/vehicle_status_v1` -> `offboard_controller`, `mission_manager`.
3. `docs/MISSIONS.md` guards table: `battery_low` (`frac` (0.2), "battery
   fraction at or below `frac`"), `failsafe_active` (no params, "PX4 reports
   an active failsafe"). Add a one-line safety-tier example under the table:

```yaml
  safety:
    - {guard: failsafe_active, to: hold_safe}
    - {guard: battery_low, params: {frac: 0.25}, to: return_to_origin}
```

**Verify**: `uv run pytest tests/unit -q -k schema` -> passes;
`rg -n "battery_status" docs/TOPICS.md` -> rows present

### Step 5: Full gate

**Verify**: `just check` -> exit 0

### Step 6: Live verification (operator-gated)

1. `just sim` -> READY. `ros2 topic list | grep -i battery` -> note the exact
   name. If it is NOT `/fmu/out/battery_status_v1`: unversioned
   `/fmu/out/battery_status` means edit the subscription + TOPICS.md rows to
   the real name and re-run `just check`; NO battery topic at all is a STOP
   condition (report; the uXRCE publication set on this PX4 build omits it).
2. `ros2 topic echo /fmu/out/battery_status_v1 --once` (real name) ->
   `remaining` is a sane fraction (SITL's simulated battery starts near 1.0
   and drains slowly).
3. Guard end-to-end: create a THROWAWAY mission copy (e.g.
   `/tmp` is fine for this file, or `config/missions/` deleted afterwards)
   of `hover.yaml` with the safety edge
   `{guard: battery_low, params: {frac: 0.99}, to: hold_safe}` - with SITL's
   battery just below full this trips within the first ticks; confirm via
   `rg "TRANSITION.*battery_low" logs/latest.log` after booting it with
   `--overlay` pointing at the copy (or `ros2 param set` + relaunch). Then
   delete the throwaway files. `just stop`.
4. Regression: `just scenario 01_arm_takeoff` -> PASS (fail-open defaults did
   not disturb an existing mission).

If you cannot run a sim, complete steps 1-5 and STOP reporting live
verification pending (the topic-name confirmation in particular).

## Test plan

Unit: the guard truth tables + boundary + defaults regression (Step 2), the
schema drift test (Step 4). Live: topic-name confirmation, a forced
`battery_low` safety transition observed in the structured log, and scenario
01 regression.

## Done criteria

- [ ] `uv run pytest tests/unit -q` passes (new guard tests included)
- [ ] `rg -n "battery_remaining|failsafe" src/core/ros_px4_template_core/lib/mission/types.py` -> both fields with defaults, appended last
- [ ] `git diff schemas/mission.schema.json` shows only two guard-enum additions
- [ ] `rg -n "battery_status" docs/TOPICS.md src/core/ros_px4_template_core/nodes/mission_manager.py` -> rows + docstring + subscription agree on ONE topic name
- [ ] `just check` exits 0
- [ ] Live Step 6 checks reported (or explicitly deferred by the operator)
- [ ] `git status` shows only in-scope files modified
- [ ] `plans/README.md` status row updated

## STOP conditions

- No battery topic exists on the live graph under either name (Step 6.1).
- `BatteryStatus` has no `remaining` field on `release/1.17` (message drift -
  report the actual fields).
- Adding the defaulted fields breaks any existing `Inputs` construction site
  (would mean a positional construction exists somewhere - report it, do not
  reorder fields).
- The `just log topics` manifest check fails after the TOPICS.md edit because
  the battery topic is absent from the live graph - reconcile the name first
  (Step 6.1), never delete the manifest row to make the check pass.

## Maintenance notes

- Follow-up candidates once real hardware data flows: `estimate_ok` from a
  real estimator-health flag, wind/geofence from PX4 events - each is "one
  field on `Inputs` + one guard", the pattern this plan establishes.
- Reviewer: guards must stay pure over the snapshot (no node state reads),
  and the defaults must remain fail-open (a template user whose PX4 build
  lacks the battery topic gets exactly today's behavior).
