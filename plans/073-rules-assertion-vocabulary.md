# Plan 073: Rules assertion vocabulary — altitude_ceiling / time_budget / keep_out_box guards + a HeldThroughout scenario sampler

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in "STOP conditions" occurs, stop and report — do not
> improvise. When done, update this plan's row in `plans/README.md` unless a
> reviewer told you they maintain the index.
>
> **Drift check (run first)**:
> `git diff --stat 6ce9aec..HEAD -- src/core/ros_px4_template_core/lib/mission src/core/ros_px4_template_core/lib/mission_inputs.py src/core/ros_px4_template_core/nodes/mission_manager.py tests/unit docs/MISSIONS.md schemas/`
> On any mismatch with the "Current state" excerpts below, STOP.

## Status

- **Priority**: P2 (direction: closes the gap between what rules documents
  demand and what missions/scenarios can assert)
- **Effort**: M
- **Risk**: LOW-MED (touches the Inputs dataclass — one new defaulted field —
  and mission_manager's snapshot; everything else is additive)
- **Depends on**: none to build. If plan 069 (load-time probe) has landed,
  the new guards must pass its probe; if it has not, write them to the same
  standard anyway (see step 2 notes) so 069 needs no rework.
- **Category**: direction / feature
- **Planned at**: commit `6ce9aec`, 2026-07-16

## Why this matters

Competition rules documents speak in constraints: "stay below 10 m", "the
run ends after 5 minutes", "do not enter the spectator zone". The mission
engine's guard vocabulary today covers markers, waypoints, battery, a radial
geofence, and estimator health — but none of those three constraint shapes.
An agent authoring a challenge (docs/CHALLENGES.md loop, plan 072) currently
has to either ignore such rules or hack them into behaviors, which the
architecture forbids. Three small pure guards close the gap. On the
verification side, scenarios can assert end-state but have no idiom for
"condition X held for the WHOLE flight" — a `HeldThroughout` sampler gives
`write_report` violation evidence instead of a hand-rolled flag per scenario.
Deliberately rejected: a `visit_order` guard — the mission state graph
already expresses ordering natively (states + transitions); encoding it again
in a guard would be the abstraction creep this project guards against.

## Current state

- `src/core/ros_px4_template_core/lib/mission/types.py:10–24` — frozen
  `Inputs` dataclass: `now, pose_enu, yaw_enu, armed, altitude_ok,
  estimate_ok, detections, detection_stability, input_ages,
  battery_remaining, failsafe_active`. No mission-elapsed field.
- `src/core/ros_px4_template_core/lib/mission/guards.py` — 15 registered
  guards, pattern (validation style to copy, from `battery_low`, lines
  83–94):

  ```python
  @guard("battery_low")
  def battery_low(inputs: Inputs, signals: dict, params: dict) -> bool:
      frac = float(params.get("frac", 0.2))
      if not 0.0 <= frac <= 1.0:
          raise ValueError(f"battery_low: 'frac' must be within [0, 1], got {frac}")
  ```

  Radial precedent: `geofence_breach` (lines 66–69) uses
  `math.hypot(...) >= radius`.
- `Inputs` constructors (ALL must gain the new field's value):
  1. `src/core/ros_px4_template_core/lib/mission_inputs.py` `build_inputs`
     (line 80) — pure builder from `MissionManagerState` (dataclass, lines
     26–46). `mission_manager.py` builds the state under its lock in
     `_snapshot` (line 207) and calls `build_inputs` at line 230; `_armed` is
     set from vehicle status at line 153.
  2. `src/core/ros_px4_template_core/lib/mission/simulate.py:152` — the
     `just mission sim` kinematic harness; `SimVehicle` arms on first GoTo
     (line 170).
  3. Unit-test `_inputs()` helpers in `tests/unit/test_mission_guards.py:26`,
     `test_mission_engine.py:26`, `test_mission_behaviors.py:26` (defaulted
     field means these keep working unchanged).
- Enforcement pair (both unit-enforced, per AGENTS.md):
  `tests/unit/test_missions_doc.py` (every registered guard needs its
  docs/MISSIONS.md Guards-table row) and `tests/unit/test_mission_schema.py`
  (committed `schemas/mission.schema.json` must match `just mission schema`
  output, generated from `known_guards()`).
- `docs/MISSIONS.md` — Guards table around line 158; params documented per
  guard.
- `tests/scenarios/_common.py` — scenario helpers (`spin_until`,
  `write_report`, `Scenario`); no throughout-the-run assertion idiom exists.
  Scenarios poll via callbacks + `done()` predicates.
- Plan 069 (if landed) probes every guard once at mission load with neutral
  inputs — guards must not raise on neutral inputs when their params are
  valid, and SHOULD raise `ValueError` immediately on invalid/missing params.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Quality gate | `just check` | exit 0 |
| Guard tests | `uv run pytest tests/unit/test_mission_guards.py tests/unit/test_mission_inputs.py tests/unit/test_mission_sim.py -q` | all pass |
| Schema regen | `just mission schema > schemas/mission.schema.json` | file updated |
| Docs/schema locks | `uv run pytest tests/unit/test_missions_doc.py tests/unit/test_mission_schema.py -q` | all pass |
| Mission dry-run | `just mission sim <name>` | verdict exit 0 |

## Scope

**In scope**:
- `lib/mission/types.py` (one defaulted field on `Inputs`)
- `lib/mission/guards.py` (three new guards)
- `lib/mission_inputs.py` + `nodes/mission_manager.py` (elapsed plumbing)
- `lib/mission/simulate.py` (elapsed plumbing in the harness)
- `tests/scenarios/_common.py` (`HeldThroughout`)
- `tests/unit/` (guard tests, inputs tests, sampler tests)
- `docs/MISSIONS.md` Guards table, `schemas/mission.schema.json` (regenerated)

**Out of scope** (do NOT touch):
- Behaviors, the engine (`engine.py`), the loader — guards only.
- Shipped missions in `config/missions/` — no mission is required to USE the
  new guards; wiring one into a shipped mission is follow-up work.
- A `visit_order` guard — rejected (see Why).
- `src/` QoS, frames, or anything outside the mission library seam.

## Git workflow

- Branch: `advisor/073-rules-assertion-vocabulary`
- Commit style: `feat(mission): altitude_ceiling, time_budget, keep_out_box guards + HeldThroughout sampler`
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: `mission_elapsed_s` on `Inputs`

Add to `Inputs` (types.py), after `failsafe_active`:

```python
mission_elapsed_s: float = 0.0
```

Semantics (document in the docstring): seconds since the vehicle FIRST
became armed in this run; `0.0` until then. Rationale: rules-document time
budgets start at takeoff, not process start (sim boots disarmed and may idle
arbitrarily long before a scenario arms it).

Plumbing:
- `mission_inputs.py`: `MissionManagerState` gains
  `first_armed_time: float | None`; `build_inputs` sets
  `mission_elapsed_s=(now - s.first_armed_time) if s.first_armed_time is not
  None else 0.0`.
- `mission_manager.py`: under the existing lock where `self._armed` is set
  (line 153), record `self._first_armed_time = <msg time now>` the first
  time armed flips True (never reset); pass it into `MissionManagerState` in
  `_snapshot`. Use the same clock source `_snapshot`'s `now` comes from —
  check what the node passes (line 245) and stay consistent.
- `simulate.py`: `SimVehicle` gains `first_armed_time: float | None = None`;
  set it where `v.armed = True` fires (line 170, and anywhere else arming
  happens); pass `mission_elapsed_s` into the `Inputs` at line 152.

**Verify**: `uv run pytest tests/unit/test_mission_inputs.py tests/unit/test_mission_sim.py -q`
→ pass (extend `test_mission_inputs.py` with: not-yet-armed → 0.0; armed at
t=5 queried at t=12 → 7.0).

### Step 2: Three guards in `guards.py`

Follow `battery_low`'s style exactly: pure over the snapshot, `ValueError`
with the guard's name for invalid params, sensible behavior on neutral
inputs (so the plan-069 probe passes).

```python
@guard("altitude_ceiling")
def altitude_ceiling(inputs: Inputs, signals: dict, params: dict) -> bool:
    """True when ENU z is at or above the ceiling. Safety-tier material."""
    if "ceiling_m" not in params:
        raise ValueError("altitude_ceiling: required param 'ceiling_m' is missing")
    ceiling = float(params["ceiling_m"])
    if ceiling <= 0.0:
        raise ValueError(f"altitude_ceiling: 'ceiling_m' must be > 0, got {ceiling}")
    return inputs.pose_enu[2] >= ceiling


@guard("time_budget")
def time_budget(inputs: Inputs, signals: dict, params: dict) -> bool:
    """True when the mission has been armed longer than the budget."""
    if "budget_s" not in params:
        raise ValueError("time_budget: required param 'budget_s' is missing")
    budget = float(params["budget_s"])
    if budget <= 0.0:
        raise ValueError(f"time_budget: 'budget_s' must be > 0, got {budget}")
    return inputs.mission_elapsed_s > budget


@guard("keep_out_box")
def keep_out_box(inputs: Inputs, signals: dict, params: dict) -> bool:
    """True when the vehicle is inside an axis-aligned ENU keep-out box."""
    required = ("x_min", "x_max", "y_min", "y_max")
    missing = [k for k in required if k not in params]
    if missing:
        raise ValueError(f"keep_out_box: required params missing: {missing}")
    x0, x1 = float(params["x_min"]), float(params["x_max"])
    y0, y1 = float(params["y_min"]), float(params["y_max"])
    z0 = float(params.get("z_min", float("-inf")))
    z1 = float(params.get("z_max", float("inf")))
    if x0 >= x1 or y0 >= y1 or z0 >= z1:
        raise ValueError("keep_out_box: each *_min must be < its *_max")
    x, y, z = inputs.pose_enu
    return (x0 <= x <= x1) and (y0 <= y <= y1) and (z0 <= z <= z1)
```

All three are intended for the safety tier (`from: null` transitions to a
return/land state), like `geofence_breach`; say so in each docstring.

**Verify**: `uv run pytest tests/unit/test_mission_guards.py -q` → pass with
the new tests (step 4).

### Step 3: Docs table + schema regen (both locks)

- Add three rows to the docs/MISSIONS.md Guards table (name, params with
  defaults/required flags, one-line meaning, "safety tier" note), matching
  the table's existing wording density.
- `just mission schema > schemas/mission.schema.json` and commit the diff.

**Verify**: `uv run pytest tests/unit/test_missions_doc.py tests/unit/test_mission_schema.py -q`
→ all pass.

### Step 4: Unit tests for the guards

In `tests/unit/test_mission_guards.py`, using its `_inputs()` helper (extend
the helper with `mission_elapsed_s` passthrough):

- altitude_ceiling: below → False; at/above → True; missing/nonpositive
  `ceiling_m` → ValueError.
- time_budget: `mission_elapsed_s=0.0` (never armed) → False regardless of
  budget; elapsed 301 vs budget 300 → True; missing/nonpositive → ValueError.
- keep_out_box: inside → True; on the face → True; outside → False; z-bounds
  optional (inside xy but above `z_max` → False); missing params and inverted
  bounds → ValueError.
- One graph-level test in `tests/unit/test_mission_sim.py`: a tiny inline
  mission with a safety transition `{guard: time_budget, params: {budget_s:
  2}, to: land}` simulated via `simulate(...)` — assert the FSM reaches
  `land` after ~2 sim-seconds of armed flight (this proves the
  simulate-side plumbing, not just the pure guard).

**Verify**: the pytest commands above → all pass.

### Step 5: `HeldThroughout` sampler in `tests/scenarios/_common.py`

```python
class HeldThroughout:
    """Continuously-sampled invariant for scenarios: 'X held for the whole run'.

    Call sample() from any callback or done() predicate; the report gets
    hard evidence (violation count, first violation time/value) instead of
    a scenario-local boolean.
    """

    def __init__(self, name: str, ok: Callable[[], bool],
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.name = name
        self._ok = ok
        self._clock = clock
        self._t0 = clock()
        self.violations = 0
        self.first_violation_t: float | None = None

    def sample(self) -> None:
        if not self._ok():
            self.violations += 1
            if self.first_violation_t is None:
                self.first_violation_t = self._clock() - self._t0

    @property
    def held(self) -> bool:
        return self.violations == 0

    def detail(self) -> dict:
        return {
            f"{self.name}_held": self.held,
            f"{self.name}_violations": self.violations,
            f"{self.name}_first_violation_s": (
                round(self.first_violation_t, 1)
                if self.first_violation_t is not None else None
            ),
        }
```

No scenario is required to adopt it in this plan (that's plan-071 territory
and future challenge scenarios); it ships with unit tests only. Add a short
"Asserting rules constraints" note to docs/CHALLENGES.md (if plan 072 has
landed) or leave a one-line pointer in the module docstring otherwise.

**Verify**: new `tests/unit/test_scenario_helpers.py` (or extend an existing
scenario-helper test file if one exists — check first) with an injected
fake clock: no violations → `held` True and `detail()` shape correct; one
failing sample at t=3 → `violations == 1`, `first_violation_s == 3.0`.

### Step 6: Full gate + optional live smoke

`just check` → exit 0. Optional (sim machine): `just mission sim hover` and
one live scenario (`just sim`, `just scenario 01_arm_takeoff`, `just stop`)
to confirm the mission_manager plumbing change is inert for existing
missions.

## Test plan

Steps 1, 4, and 5 carry the tests: inputs-elapsed unit tests, per-guard
truth-table + validation tests, one simulate-level time_budget graph test,
injected-clock sampler tests, plus the two enforcement locks (docs table,
schema). Existing guard/engine/behavior tests must pass untouched except the
`_inputs()` helper extension.

## Done criteria

- [ ] `rg -n "altitude_ceiling|time_budget|keep_out_box" src/core/ros_px4_template_core/lib/mission/guards.py` → three registered guards
- [ ] `Inputs.mission_elapsed_s` populated by mission_manager (via `build_inputs`) AND `simulate.py`
- [ ] docs/MISSIONS.md Guards table has the three rows; `schemas/mission.schema.json` regenerated; `test_missions_doc.py` + `test_mission_schema.py` pass
- [ ] simulate-level test proves a `time_budget` safety transition fires
- [ ] `HeldThroughout` in `_common.py` with injected-clock unit tests
- [ ] `just check` → exit 0
- [ ] `plans/README.md` status row updated

## STOP conditions

- Adding `mission_elapsed_s` breaks a frozen-dataclass consumer you didn't
  anticipate (`rg "Inputs(" src/ tests/` first; the field is defaulted, so
  positional-construction breakage means someone constructs Inputs
  positionally — report, don't reorder fields).
- Plan 069's load probe (if landed) rejects a shipped mission after your
  change — your guards must be additive; nothing shipped uses them yet.
- You find yourself adding mission-ordering logic (visit_order or similar) —
  rejected by design; the state graph expresses ordering.

## Maintenance notes

- Guard param validation raising `ValueError` eagerly is what makes plan
  069's load-time probe useful — keep that style for all future guards.
- `mission_elapsed_s` starts at FIRST arm and never resets; if a future
  multi-flight mission needs per-flight budgets, that is a new field, not a
  semantics change to this one.
- When plan 072's CHALLENGES.md exists, its "representable vs verifiable"
  section should list these three guards as the rules-constraint vocabulary.
