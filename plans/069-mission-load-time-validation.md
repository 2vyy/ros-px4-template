# Plan 069: mission YAML param errors fail at load (`just mission validate`), never inside the flying FSM

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in "STOP conditions" occurs, stop and report — do not
> improvise. When done, update this plan's row in `plans/README.md` unless a
> reviewer told you they maintain the index.
>
> **Drift check (run first)**:
> `git diff --stat 6ce9aec..HEAD -- src/core/ros_px4_template_core/lib/mission/loader.py src/core/ros_px4_template_core/lib/mission/guards.py src/core/ros_px4_template_core/lib/mission/behaviors.py tools/mission_cli.py tests/unit/`
> On any mismatch with the "Current state" excerpts below, STOP.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: LOW-MED (a load-time probe could reject a legitimate mission — gated by running it against every shipped mission)
- **Depends on**: none
- **Category**: bug / correctness
- **Planned at**: commit `6ce9aec`, 2026-07-16

## Why this matters

The loader promises "a malformed mission fails fast at startup, not
mid-flight" (docs/MISSIONS.md), but guard/behavior params are only touched
when a tick evaluates them. `battery_low` range-checks `frac` PER TICK and
raises `ValueError` inside `engine.tick` — for a safety guard that runs every
tick from any state, a YAML typo (`frac: 20`) takes `mission_manager` down at
runtime, uncaught. Any non-numeric param (`tolerance_m: fast`) does the same
via `float(...)`. `just mission validate` cannot catch either (it only loads),
and `just mission sim` crashes with a raw traceback because `simulate()` runs
outside its try/except. Separately, `load_mission_file` computes
`base_dir=p.resolve().parents[2]`, which raises `IndexError` for a mission
path fewer than three levels deep (e.g. `/tmp/x.yaml` — confirmed) and
resolves relative `path_file` against a wrong directory for any non-standard
location. After this plan, every shipped mission still loads identically, a
bad param is a clean `MissionError` at load, and shallow paths work.

## Current state

- `src/core/ros_px4_template_core/lib/mission/loader.py` (86 lines total):
  - `load_mission_file` (lines 80–83):
    ```python
    def load_mission_file(path: str | Path) -> Mission:
        p = Path(path)
        doc = yaml.safe_load(p.read_text(encoding="utf-8"))
        return load_mission_dict(doc, base_dir=p.resolve().parents[2])
    ```
    For `config/missions/demo.yaml`, `parents[2]` = the project root — that is
    the documented `path_file` base ("resolved relative to the project root",
    docs/MISSIONS.md). For `/tmp/x.yaml`, `parents` is `(/tmp, /)` →
    `IndexError`.
  - `_resolve_waypoints` (lines 19–35) already validates inline waypoints at
    load via `_split_waypoint_entry`, raising `MissionError` — this is the
    load-time validation pattern to extend.
  - `load_mission_dict` (lines 38–77) validates behavior/guard NAMES, edges,
    initial/terminal. It never calls a guard or behavior.
- `src/core/ros_px4_template_core/lib/mission/guards.py`:
  - `battery_low` (lines 83–94) — the per-tick raise:
    ```python
    frac = float(params.get("frac", 0.2))
    if not 0.0 <= frac <= 1.0:
        raise ValueError(f"battery_low: 'frac' must be within [0, 1], got {frac}")
    ```
  - Other guards call `float(params.get(...))` / `int(tid)` per evaluation
    (`marker_fresh` line 48, `marker_stable` 53–57, `marker_lost` 63,
    `geofence_breach` 68, `inputs_stale` 80).
- `src/core/ros_px4_template_core/lib/mission/behaviors.py` — behaviors
  likewise coerce params per tick (`float(params.get(...))` at ~lines 27–32,
  63, 99–102, 128–130, 184–189).
- `src/core/ros_px4_template_core/lib/mission/types.py` — `Inputs` is the
  frozen snapshot dataclass; see `tests/unit/test_mission_guards.py` lines
  1–40 for the `_inputs(...)` construction helper (now, pose_enu, yaw_enu,
  armed, altitude_ok, estimate_ok, detections, detection_stability,
  input_ages, battery_remaining, failsafe_active).
- `tools/mission_cli.py`:
  - `validate`/`show`/`sim` each wrap ONLY `load_mission_file` in
    `try/except Exception` → exit 2 (e.g. lines ~194–198, ~219–222).
  - `sim_cmd` (lines ~203–235) then calls `simulate(m, ...)` OUTSIDE that
    try — a param error raised during ticking is a raw traceback.
  - `mission_path(name)` resolves names to `config/missions/<name>.yaml` and
    passes through direct `.yaml` paths (so `/tmp/x.yaml` is reachable from
    the CLI).
- Engine call path: `engine.tick` → `_first_fired` evaluates guards;
  `mission_manager._tick` has NO try/except around it (only
  `KeyboardInterrupt` at `main`). This plan does NOT add one — load-time
  rejection is the fix; a crash on a genuinely new runtime bug should stay
  loud.
- Six shipped missions: `config/missions/*.yaml` (demo, hover, marker_hover,
  precision_land, search_relocalize, yaw_demo). `tests/unit/test_mission_sim.py`
  already globs and simulates all of them — your regression net.
- Convention: loader errors are `MissionError` with the state/transition
  context in the message (`f"state '{name}': unknown behavior '{bname}'"`).
  Match it.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Quality gate | `just check` | exit 0 |
| Mission suite | `uv run pytest tests/unit/test_mission_sim.py tests/unit/test_mission_loader.py -q` (create the latter if absent — check `ls tests/unit/ \| grep loader` first) | all pass |
| All missions still valid | `uv run python tools/mission_cli.py list` then `validate` each | exit 0, `OK` |
| Shallow path | `cp config/missions/hover.yaml /tmp/claude/x.yaml && uv run python tools/mission_cli.py validate /tmp/claude/x.yaml` | exit 0, no IndexError |

## Scope

**In scope**:
- `src/core/ros_px4_template_core/lib/mission/loader.py`
- `tools/mission_cli.py` (`sim_cmd` error handling only)
- `tests/unit/test_mission_loader.py` (create or extend)

**Out of scope** (do NOT touch):
- `guards.py` / `behaviors.py` — their per-tick coercions stay; the probe
  makes them fire at load. (Do NOT move `battery_low`'s range check out of the
  guard: it also protects direct engine embedding.)
- `engine.py`, `mission_manager.py` — no runtime try/except; crash-fast on
  genuine bugs is deliberate.
- `simulate.py`, the schema generator, docs/MISSIONS.md tables.

## Git workflow

- Branch: `advisor/069-mission-load-validation`
- Commit style: `fix(mission): validate guard/behavior params at load; shallow-path base_dir`
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Characterize current behavior (tests first)

In `tests/unit/test_mission_loader.py` (create if absent; import style per
`tests/unit/test_mission_sim.py`), add failing tests:

```python
def test_bad_guard_param_rejected_at_load() -> None:
    doc = {"mission": {"initial": "a",
        "states": {"a": {"behavior": "hold", "params": {}}},
        "safety": [{"guard": "battery_low", "params": {"frac": 20}, "to": "a"}]}}
    with pytest.raises(MissionError, match="battery_low"):
        load_mission_dict(doc)

def test_non_numeric_behavior_param_rejected_at_load() -> None:
    doc = {"mission": {"initial": "a",
        "states": {"a": {"behavior": "hold", "params": {"tolerance_m": "fast"}}}}}
    with pytest.raises(MissionError, match="state 'a'"):
        load_mission_dict(doc)

def test_shallow_mission_path_loads(tmp_path) -> None:
    src = ROOT / "config" / "missions" / "hover.yaml"
    dst = tmp_path / "x.yaml"          # tmp_path is deep enough; ALSO cover
    dst.write_text(src.read_text())    # the 2-level case via monkeypatched Path if cheap
    load_mission_file(dst)             # must not raise
```

Run: `uv run pytest tests/unit/test_mission_loader.py -q` → the two new
param tests FAIL (load currently succeeds), shallow-path may fail with
IndexError only for paths <3 deep — assert at least that a plain temp path
loads.

### Step 2: Fix `base_dir` for shallow paths

```python
def load_mission_file(path: str | Path) -> Mission:
    p = Path(path).resolve()
    doc = yaml.safe_load(p.read_text(encoding="utf-8"))
    # path_file is documented as project-root-relative for the standard
    # config/missions/ layout (parents[2] == repo root). For missions loaded
    # from anywhere shallower/elsewhere, fall back to the mission file's own
    # directory rather than crashing.
    base_dir = p.parents[2] if len(p.parents) > 2 else p.parent
    return load_mission_dict(doc, base_dir=base_dir)
```

**Verify**: `uv run pytest tests/unit/test_mission_loader.py::test_shallow_mission_path_loads -q`
→ pass. `uv run pytest tests/unit/test_mission_sim.py -q` → all pass (shipped
missions unaffected).

### Step 3: Load-time probe of every guard and behavior

In `load_mission_dict`, after the `Mission` is fully constructed (all names
validated), add a probe pass BEFORE returning:

```python
_probe_mission(states, safety + transitions)
```

with:

```python
def _neutral_inputs() -> "Inputs":
    from ros_px4_template_core.lib.mission.types import Inputs
    return Inputs(now=0.0, pose_enu=(0.0, 0.0, 0.0), yaw_enu=0.0, armed=False,
                  altitude_ok=False, estimate_ok=True, detections=(),
                  detection_stability={}, input_ages={}, battery_remaining=None,
                  failsafe_active=False)  # match the REAL field list in types.py


def _probe_mission(states, edges) -> None:
    """Evaluate every behavior and guard once against a neutral snapshot so
    param type/range errors surface at load, not mid-flight. Results are
    discarded; behaviors get a throwaway scratch dict."""
    from ros_px4_template_core.lib.mission.registry import get_behavior, get_guard
    inputs = _neutral_inputs()
    for name, sd in states.items():
        try:
            get_behavior(sd.behavior)({}, inputs, dict(sd.params))
        except MissionError:
            raise
        except Exception as e:
            raise MissionError(f"state '{name}': behavior '{sd.behavior}' params invalid: {e}") from e
    for t in edges:
        try:
            get_guard(t.guard)(inputs, {}, dict(t.params))
        except Exception as e:
            raise MissionError(f"transition to '{t.to}': guard '{t.guard}' params invalid: {e}") from e
```

Adjust names to the REAL `Inputs` fields (`types.py`), the real registry
accessors (`registry.py` — `rg "def get_" src/core/ros_px4_template_core/lib/mission/registry.py`),
and the real `TransitionDef` attribute names. The probe must pass a COPY of
params (behaviors may mutate scratch, never params — but copy defensively).

**Verify**: `uv run pytest tests/unit/test_mission_loader.py -q` → the two
param tests now PASS. Then the safety gate:
`uv run pytest tests/unit/ -q` → ALL pass, in particular every
`test_mission_sim.py` case (all six shipped missions still load and
terminate). If any shipped mission fails the probe: STOP (see below).

### Step 4: `mission sim` reports tick-time errors cleanly

In `tools/mission_cli.py` `sim_cmd`, wrap the `simulate(...)` call (and the
result handling that immediately follows) in:

```python
try:
    result = simulate(...)
except Exception as e:
    typer.echo(f"mission sim failed: {type(e).__name__}: {e}", err=True)
    raise typer.Exit(2) from None
```

**Verify**: craft `/tmp/claude/bad.yaml` (hover mission + safety
`battery_low` with `frac: 20`) →
`uv run python tools/mission_cli.py validate /tmp/claude/bad.yaml` → exit 2
with a `battery_low` message (probe catches it at load, so `sim` never even
ticks it). `uv run python tools/mission_cli.py sim hover` → unchanged OK.

### Step 5: Full gate

**Verify**: `just check` → exit 0.

## Test plan

All in `tests/unit/test_mission_loader.py` (pattern: `test_mission_sim.py`):
bad `battery_low.frac` (load fails, message names the guard); non-numeric
behavior param (load fails, message names the state); every
`config/missions/*.yaml` loads (glob test — may already exist in
`test_mission_sim.py`; don't duplicate, reference it); shallow-path load; a
`path_file` mission still resolves from the standard layout (there is a
shipped mission using `path_file` — `rg path_file config/missions/` — assert
it loads with populated waypoints).

## Done criteria

- [ ] `load_mission_dict` rejects out-of-range `battery_low.frac` and non-numeric params with `MissionError` naming the state/guard
- [ ] `uv run python tools/mission_cli.py validate /tmp/claude/bad.yaml` → exit 2, clean one-line error
- [ ] Shallow path: `validate /tmp/claude/x.yaml` (copied hover) → exit 0
- [ ] All six shipped missions: `just mission sim <name>` unchanged verdicts
- [ ] `uv run pytest tests/unit/ -q` → all pass; `just check` → exit 0
- [ ] `plans/README.md` status row updated

## STOP conditions

- ANY shipped mission in `config/missions/` fails the step-3 probe: the
  neutral snapshot triggers a false rejection. Report which
  behavior/guard raised and with what — do not "fix" the mission or weaken
  the guard to make it pass.
- The `Inputs` dataclass fields differ from the excerpt in a way that makes a
  neutral snapshot ambiguous (e.g. a new required field with no obvious
  neutral value).
- The fix appears to require editing `guards.py`/`behaviors.py`.

## Maintenance notes

- New guards/behaviors are automatically covered by the probe — but authors
  must keep them SAFE to evaluate on a neutral snapshot (pure, no I/O). Add
  that sentence to the "Adding a behavior or guard" checklist in
  docs/MISSIONS.md if a follow-up docs pass happens (deliberately not in this
  plan's scope to keep the docs-table unit tests untouched).
- Plan 073 adds new guards (`altitude_ceiling`, `time_budget`,
  `keep_out_box`); they must pass this probe — its author is told so.
