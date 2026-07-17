# Plan 059: Engine polish — safety edges stop re-firing into their own state; malformed inline waypoints fail at load

> **Executor instructions**: Follow this plan step by step, verifying each
> step. On any STOP condition, stop and report. When done, update
> `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 01f94c7..HEAD -- src/core/ros_px4_template_core/lib/mission/engine.py src/core/ros_px4_template_core/lib/mission/loader.py src/core/ros_px4_template_core/lib/mission/behaviors.py tests/unit/test_mission_engine.py tests/unit/test_mission_loader.py`
> On any mismatch with the excerpts below, STOP.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW–MED (part A changes engine semantics in a persistent-fault situation; the behavior change is deliberate and specified below)
- **Depends on**: 054 (use its `simulate()` harness for the persistent-fault test if it has landed; hand-scripted ticks otherwise)
- **Category**: bug
- **Planned at**: commit `01f94c7`, 2026-07-10

## Why this matters

**A — safety self-transition churn.** Safety edges are evaluated every tick
regardless of the current state. While a safety condition persists (e.g.
`geofence_breach` during the flight back, or a future persistent-fault
`hold_safe`), the engine re-fires the edge INTO the state it already
occupies: a `TRANSITION` event is logged every tick (log spam that buries
real events) and the state's scratch is wiped every tick. For `hold_safe`
(behavior `hold`), the scratch wipe means the hold target is re-captured from
the LIVE pose each tick instead of freezing where the fault occurred — a
drifting vehicle "holds" a moving point. Currently masked (the two live
safety guards coincide with frozen/converging poses) but it booby-traps every
future stateful safety behavior.

**B — malformed inline waypoints explode per-tick instead of at load.**
`_split_waypoint_entry` raises `ValueError` for wrong-arity entries, but it
runs inside `follow_waypoints` on every tick; the loader validates behaviors,
guards, and edges — not inline `waypoints`. A bad mission passes
`just mission validate`, then throws in the tick callback forever: the
vehicle silently holds its last setpoint with no mission-level failure
surfaced. The behavior's own docstring promises "fails fast at
load/first-tick" — make the load half true.

## Current state

`src/core/ros_px4_template_core/lib/mission/engine.py:35-69` (`tick`):

```python
fired = _first_fired(mission.safety, inputs, signals)
tier = "safety"
if fired is None and ctx.state not in mission.terminal:
    outgoing = tuple(t for t in mission.transitions if t.src == ctx.state)
    fired = _first_fired(outgoing, inputs, signals)
    tier = "mission"

if fired is not None:
    ctx.events.append({... "TRANSITION" ...})
    ctx.scratch.pop(ctx.state, None)
    ctx.state = fired.dst
    ctx.scratch.pop(ctx.state, None)  # fresh entry
    command, _ = _run(ctx, mission, inputs)
```

No guard against `fired.dst == ctx.state`. (Mission-tier edges can also
self-loop if a YAML author writes `from: X, to: X`, but no shipped mission
does; the fix below covers both tiers uniformly.)

`lib/mission/loader.py:18-26` — `_resolve_waypoints` only handles the
`path_file` branch; inline `waypoints` pass through unvalidated.
`lib/mission/behaviors.py:39-56` — `_split_waypoint_entry(entry, index)`
raises `ValueError` on arity ≠ 3/4; `:80-86` `follow_waypoints` calls it per
tick over `params.get("waypoints", [])`.

Specified new semantics for A (implement exactly this):
**when the winning edge's `dst == ctx.state`, treat the tick as a no-op
transition — do not append a TRANSITION event, do not pop scratch, do not
change state; the behavior keeps running with its existing scratch.** The
first entry INTO the state (from a different state) is unchanged.

## Commands you will need

| Purpose | Command | Expected |
|---------|---------|----------|
| Quality gate | `just check` | exit 0 |
| Targeted | `uv run pytest tests/unit/test_mission_engine.py tests/unit/test_mission_loader.py tests/unit/test_mission_behaviors.py -q` | all pass |
| Mission CLI | `uv run tasks.py mission validate demo` | `OK demo: ...` |
| Live regression | `just scenario 06_search_relocalize` | PASS |

## Scope

**In scope**:
- `lib/mission/engine.py` (the `dst == ctx.state` no-op)
- `lib/mission/loader.py` (validate inline waypoints at load)
- `tests/unit/test_mission_engine.py`, `tests/unit/test_mission_loader.py` (extend)
- `docs/MISSIONS.md` — one sentence in the safety-tier section: a safety edge
  whose target is the current state does not re-enter it (scratch persists)

**Out of scope**:
- `behaviors.py` — `_split_waypoint_entry` stays where it is (the loader will
  import it; both `lib/mission/` modules, no layering issue). Do NOT remove
  the per-tick call (defense in depth for programmatically-built missions).
- `hold` behavior's scratch-capture logic — correct once self-transitions stop wiping it

## Git workflow

- Branch: `advisor/059-engine-polish`
- Two commits: `fix(mission): safety edges no longer re-fire into the current state`,
  `fix(mission): validate inline waypoints at load`

## Steps

### Step 1: Engine no-op on self-transition

In `tick`, after computing `fired`:

```python
if fired is not None and fired.dst == ctx.state:
    fired = None  # persistent condition, already in the target state: no re-entry
```

Place it BEFORE the `if fired is not None:` block so events/scratch/state all
stay untouched. Note the mission tier is only evaluated when the safety tier
didn't fire — a persisting safety condition therefore also keeps suppressing
mission-tier transitions out of the safety state, which is today's behavior
and REMAINS so (deliberate: the vehicle stays in the safe state until the
condition clears; document this in the MISSIONS.md sentence).

**Verify**: `uv run pytest tests/unit/test_mission_engine.py -q` → existing
tests still pass (they never assert a self-re-fire).

### Step 2: Engine tests

Add to `test_mission_engine.py` (reuse its `_inputs`/`_mission` helpers):

- Persistent safety condition: tick 3× with `estimate_ok=False` from the
  `hold_safe` state → exactly ONE TRANSITION event total (the initial entry
  from `takeoff`), `ctx.state == "hold_safe"` throughout, and the `hold`
  scratch (`x/y/z`) captured on entry SURVIVES ticks 2-3 while the pose in
  `_inputs` moves — assert the returned `GoTo` keeps the tick-1 coordinates
  (this is the "freeze at fault point" property).
- Condition clears: after `estimate_ok=True`, mission-tier transitions work
  again (hold_safe has no outgoing edge in the helper mission — extend the
  helper or build a local mission with one to show recovery).
- Mission-tier self-loop `from: X, to: X` with a firing guard → no event, no
  scratch wipe.
- If plan 054 landed: also run `simulate()` over `demo.yaml` with a script
  forcing `estimate_ok=False` from t=5 s for 10 s → `events` contain exactly
  one `to=hold_safe` TRANSITION.

**Verify**: `uv run pytest tests/unit/test_mission_engine.py -q` → all pass.

### Step 3: Loader validates inline waypoints

In `loader.py` `_resolve_waypoints`, after the existing `path_file` branch,
add validation of an inline list:

```python
from ros_px4_template_core.lib.mission.behaviors import _split_waypoint_entry

if "waypoints" in params:
    for i, entry in enumerate(params["waypoints"]):
        try:
            _split_waypoint_entry(tuple(entry), i)
        except (ValueError, TypeError) as e:
            raise MissionError(f"state waypoints: {e}") from e
```

Import note: check for an import cycle first — `behaviors.py` imports from
`registry`/`commands`/`detection`/`types`/`frames`, NOT from `loader`, so
`loader → behaviors` is acyclic. If ruff flags a private-name import, either
export a public `validate_waypoint_entry` alias from `behaviors.py` or move
`_split_waypoint_entry` to a shared spot in `lib/mission/types.py` — smallest
diff wins.

**Verify**: `uv run tasks.py mission validate demo` → OK (all six real
missions still validate: run `uv run tasks.py mission list` then validate each,
or rely on the schema test + Step 4 tests).

### Step 4: Loader tests

Add to `test_mission_loader.py` (match its hand-built-dict style,
`:10-30`):

- inline `waypoints: [[1, 2]]` (arity 2) → `MissionError` naming the entry index
- inline `waypoints: [[1, 2, 3, 90, 5]]` (arity 5) → `MissionError`
- inline `waypoints: [[1, 2, 3], [4, 5, 6, 90]]` → loads fine
- non-numeric entry `[["a", 2, 3]]` → `MissionError` (the float() cast raises
  ValueError; confirm the except clause catches it)

**Verify**: `uv run pytest tests/unit/test_mission_loader.py -q` → all pass.

### Step 5: Full gates

`just check` → exit 0. Live: `just scenario 06_search_relocalize` → PASS
(exercises safety edges + search behavior); `just scenario 08_precision_land`
→ PASS (marker_lost_signal transitions unaffected).

## Done criteria

- [ ] Persistent-safety test proves: one TRANSITION event, frozen hold target
- [ ] Self-loop mission-tier edge is a no-op
- [ ] Malformed inline waypoints fail `just mission validate` with a MissionError naming the index
- [ ] All six real missions still validate; `just check` exit 0
- [ ] Scenarios 06 and 08 PASS (operator)
- [ ] docs/MISSIONS.md documents the no-re-entry semantics
- [ ] `plans/README.md` row updated

## STOP conditions

- Any existing test asserts the OLD self-re-fire behavior (none found at
  planning time) — reconcile with the test author intent before changing it.
- A real mission intentionally uses a self-loop safety edge (grep
  `config/missions/` for a safety `to:` equal to a state that a safety
  condition would occupy persistently) — none exists at `01f94c7`; if one
  appeared, STOP.
- The loader import of `_split_waypoint_entry` creates a cycle at runtime
  (`just check` build failure) — use the types.py relocation fallback, and if
  that also tangles, STOP.

## Maintenance notes

- Plan 054's harness makes future engine semantic changes cheap to prove —
  keep engine tests at that level where possible.
- The "safety condition persists ⇒ mission tier suppressed" property is now
  documented; anyone adding a `hold_safe → resume` recovery edge must route
  it through the safety condition CLEARING first.
