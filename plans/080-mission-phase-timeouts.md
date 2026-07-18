# Plan 080: mission-level deadlines - `phase_timeout` guard + time-in-state in the engine

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in "STOP conditions" occurs, stop and report - do not
> improvise. When done, update this plan's row in `plans/README.md`.
>
> **Drift check (run first)**: written against main `82c21d0`. Confirm:
> - `rg "mission_elapsed_s" src/core/ros_px4_template_core/lib/mission/types.py`
>   hits (plan 073 landed). If not: STOP.
> - `rg "state_elapsed_s" src/` returns nothing (this plan introduces it).
> - `rg "entered_at" src/core/ros_px4_template_core/lib/mission/engine.py`
>   returns nothing.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: LOW-MED (engine change is additive; mission wiring uses generous
  values and is gated by `just mission sim` + live e2e)
- **Depends on**: none (independent of 081-083; land first)
- **Category**: agent-first CLI redesign (spec: `plans/079-agent-first-cli-design.md`)
- **Planned at**: commit `82c21d0`, 2026-07-17

## Why this matters

Layer 1 of the spec's termination guarantee: nothing in the mission runtime
today bounds time-in-state. A mission that never reaches `armed_at_altitude`
sits in `takeoff` forever; the only thing that ends the run is the scenario's
own timeout (and nothing ends a `just sim --overlay auto_arm` free flight).
The global armed-time bound already exists (`time_budget` guard, plan 073)
but no shipped mission uses it, and there is no per-phase bound at all.

Design (locked in the spec): per-phase `phase_timeout` guard + global
`time_budget` safety edge; breach transitions to the mission's safe state and
emits a normal `TRANSITION ... guard=phase_timeout` event. One deviation from
the spec's wording, decided here: the abort target is the mission's existing
`hold_safe` state (safe hover), NOT a land+disarm phase - no plain `land`
behavior exists and adding one is scope creep this plan rejects. The FSM
event line is the signal; layers 2/3 (plan 081's supervisor) end the run.

## Tasks

### Task 1: engine tracks time-in-state, exposes reserved signal `state_elapsed_s`

**Files**: modify `src/core/ros_px4_template_core/lib/mission/engine.py`;
test `tests/unit/test_mission_engine.py`.

- [ ] Step 1: failing tests in `tests/unit/test_mission_engine.py` (reuse the
      file's existing mission-building helpers; if it builds missions via
      `load_mission_dict`, do the same):

```python
def test_state_elapsed_signal_grows_and_resets():
    # Mission: a --(reached)--> b, behavior signals nothing until told.
    # Tick 1 at now=10.0: entered_at is set, state_elapsed_s == 0.0.
    # Tick 2 at now=14.0: state_elapsed_s == 4.0 (visible to guards).
    # Fire the transition at now=15.0, then tick at now=17.0:
    # state_elapsed_s == 2.0 (reset on entry to b).
    ...

def test_probe_neutral_inputs_unaffected():
    # load_mission_dict on a mission using phase_timeout must still load:
    # _probe_mission calls guards with signals={} and the guard must return
    # False (not raise) when only params are valid.
    ...
```

Assert via a probe guard registered in the test that records the `signals`
dict it was called with (the pattern other engine tests use), not by reaching
into engine internals.

- [ ] Step 2: `uv run pytest tests/unit/test_mission_engine.py -q` fails on
      the new tests.
- [ ] Step 3: implement in `engine.py`:

```python
@dataclass
class MissionContext:
    state: str
    scratch: dict[str, dict] = field(default_factory=dict)
    events: list[dict] = field(default_factory=list)
    entered_at: float | None = None  # inputs.now at current-state entry
```

In `tick()`, after `command, signals = _run(ctx, mission, inputs)` and before
the safety `_first_fired` call:

```python
    if ctx.entered_at is None:
        ctx.entered_at = inputs.now
    # Reserved engine-injected signal (documented in docs/MISSIONS.md):
    # seconds since the current state was entered. Behaviors must not set it.
    signals["state_elapsed_s"] = max(0.0, inputs.now - ctx.entered_at)
```

In the `if fired is not None:` block, after `ctx.state = fired.dst`:

```python
        ctx.entered_at = inputs.now
```

- [ ] Step 4: `uv run pytest tests/unit/test_mission_engine.py -q` passes;
      full `uv run pytest tests/unit/ -q` passes (simulate() and
      mission_manager construct `MissionContext(state=...)` positionally or
      by keyword - the new field has a default, so no call-site changes).
- [ ] Step 5: commit `feat(mission): engine tracks time-in-state via reserved state_elapsed_s signal`

### Task 2: `phase_timeout` guard

**Files**: modify `src/core/ros_px4_template_core/lib/mission/guards.py`;
test `tests/unit/test_mission_guards.py`.

- [ ] Step 1: failing tests:

```python
def test_phase_timeout_fires_after_budget():
    g = get_guard("phase_timeout")
    assert g(_inputs(), {"state_elapsed_s": 31.0}, {"timeout_s": 30}) is True
    assert g(_inputs(), {"state_elapsed_s": 29.0}, {"timeout_s": 30}) is False

def test_phase_timeout_empty_signals_is_false():
    # _probe_mission calls guards with signals={}; must not raise.
    assert get_guard("phase_timeout")(_inputs(), {}, {"timeout_s": 30}) is False

def test_phase_timeout_param_validation():
    with pytest.raises(ValueError):
        get_guard("phase_timeout")(_inputs(), {}, {})
    with pytest.raises(ValueError):
        get_guard("phase_timeout")(_inputs(), {}, {"timeout_s": 0})
```

(`_inputs()` = whatever neutral-Inputs helper the file already uses.)

- [ ] Step 2: run, confirm FAIL (unknown guard).
- [ ] Step 3: implement in `guards.py`, next to `time_budget`:

```python
@guard("phase_timeout")
def phase_timeout(inputs: Inputs, signals: dict, params: dict) -> bool:
    """True after timeout_s seconds in the current state (engine-injected
    ``state_elapsed_s`` signal). Intended for per-state mission-tier edges."""
    if "timeout_s" not in params:
        raise ValueError("phase_timeout: required param 'timeout_s' is missing")
    timeout = _as_float(params["timeout_s"], "phase_timeout", "timeout_s")
    if timeout <= 0.0:
        raise ValueError(f"phase_timeout: 'timeout_s' must be > 0, got {timeout}")
    return float(signals.get("state_elapsed_s", 0.0)) > timeout
```

- [ ] Step 4: tests pass.
- [ ] Step 5: commit `feat(mission): phase_timeout guard bounds time-in-state`

### Task 3: schema + docs (unit-enforced)

**Files**: modify `docs/MISSIONS.md`, regenerate `schemas/mission.schema.json`.

- [ ] Step 1: add the `phase_timeout` row to the Guards table in
      `docs/MISSIONS.md` (params: `timeout_s` required, > 0; note "reads the
      engine-injected `state_elapsed_s` signal"). Add one sentence to the
      signals/behaviors prose: `state_elapsed_s` is reserved and
      engine-injected; behaviors must not set it.
- [ ] Step 2: `just mission schema > schemas/mission.schema.json`
- [ ] Step 3: `just check` passes (test_missions_doc + schema drift guard
      both green).
- [ ] Step 4: commit `docs(missions): phase_timeout guard + reserved state_elapsed_s signal`

### Task 4: wire deadlines into the shipped missions

**Files**: modify `config/missions/{demo,marker_hover,precision_land,search_relocalize,yaw_demo}.yaml`
(NOT `hover.yaml` - its initial state is terminal, nothing to bound);
test `tests/unit/test_mission_sim.py`.

Pattern per mission (values are generous - roughly 2x the observed e2e phase
durations - because a false abort in e2e is worse than a slow abort):

- every non-terminal, non-`hold_safe` state gets a mission-tier edge
  `{from: <state>, guard: phase_timeout, params: {timeout_s: <N>}, to: hold_safe}`
  appended LAST in `transitions` (guards evaluate in order; timeout must
  never outrank a real progress guard on the same tick),
- one safety-tier edge
  `{guard: time_budget, params: {budget_s: 300}, to: hold_safe}` appended
  LAST in `safety` (after `estimate_invalid` / `inputs_stale`).

Concrete values: `takeoff: 60`, waypoint-following states (`follow`,
`approach`, `search`): 120, `descend`: 90, `reacquire`: 60, marker-hover
hold states: 120.

- [ ] Step 1: add a unit test in `tests/unit/test_mission_sim.py` proving
      boundedness end to end:

```python
def test_phase_timeout_bounds_a_stalled_mission():
    # Inline mission whose only progress guard never fires; phase_timeout
    # must route it to hold_safe. Drive simulate()/tick with now advancing
    # past 5.0 and assert a TRANSITION event with guard == "phase_timeout".
    ...
```

- [ ] Step 2: edit the five YAMLs per the pattern.
- [ ] Step 3: `just mission validate` exits 0 for all six missions;
      `just mission sim <name>` for all six still terminates with the SAME
      terminal state as before the edit (run before/after; the generous
      timeouts must not fire under simulate's synthetic schedule).
- [ ] Step 4: `just check` passes.
- [ ] Step 5: commit `feat(missions): per-phase timeouts + global time_budget to hold_safe`

### Task 5: live gate (operator)

- [ ] `just scenario 01_arm_takeoff` PASS (hover mission untouched).
- [ ] `just scenario 03_waypoint` PASS (demo mission with timeouts wired;
      confirms no false-fire in real flight).
- [ ] `just test e2e` all 8 PASS, exit 0.
- [ ] `rg "guard=phase_timeout" logs/latest.log` returns NOTHING after the
      passing cycle (timeouts armed but never fired).
- [ ] Update `plans/README.md` row.

## STOP conditions

- Any `just mission sim` trace changes terminal state after Task 4: the
  synthetic schedule is outrunning a timeout value. Raise that mission's
  values (do not restructure the mission) and re-verify; if raising past 2x
  does not fix it, STOP and report.
- If `test_missions_doc` counts guards differently than expected (registry
  drift since `82c21d0`): reconcile the table, do not skip the test.
- Any live scenario FAIL naming `phase_timeout` in its transition history:
  STOP - a value is too tight for real flight.

## Explicitly out of scope

- A `land` behavior / land-and-disarm abort phase (spec wording deviation
  recorded above; revisit only with a real demand).
- Wiring `phase_timeout` into scenario predicates or the supervisor (that is
  plans 081/082 territory).
- `hover.yaml` (terminal-at-start; the scenario layer bounds it).
