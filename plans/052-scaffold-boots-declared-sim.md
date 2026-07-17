# Plan 052: A freshly scaffolded scenario boots its declared sim config (kill the `platforms = []` dead-end)

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving on. On
> any STOP condition, stop and report. When done, update `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 01f94c7..HEAD -- tasks.py tools/capabilities.py tests/unit/test_capabilities.py tests/unit/test_scenario_sim_config.py`
> On any mismatch with the excerpts below, STOP.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none (pairs with plan 053; either order)
- **Category**: dx
- **Planned at**: commit `01f94c7`, 2026-07-10

## Why this matters

The repo's core promise is that an agent can add a new scenario and have it
e2e-verified quickly. Today the scaffold's own printed instructions produce a
dead-end: `just scenario-new` prints a `capabilities.toml` snippet with
`platforms = []`, but every consumer filters on `platform in cap["platforms"]`.
The result: `just scenario <new>` silently ignores the `sim_vision`/`sim_overlay`
the agent just declared and runs against whatever sim happens to be up — a
vision scenario boots a no-vision sim and fails confusingly. Getting "sim"
into `platforms` today requires `just cap mark`, which stamps
`status = "verified"` **before the scenario has ever passed** — a
chicken-and-egg that teaches agents to lie to the registry.

Design decision (implement as specified): `platforms` declares **where the
scenario is intended to run**; `status` records verification. The scaffold
should print `platforms = ["sim"]` and `status = "unverified"`. Launch-config
resolution and verification-recording both key off `platforms`; only
`cap mark` touches `status`/`last_verified`. This keeps `scenario_sim_configs`
(the e2e roster) intact — a declared-but-unverified scenario DOES run in e2e,
which is exactly what plan 053 wants.

## Current state

- `tasks.py:1056-1062` — the scaffold prints:

  ```python
  print(f"[capabilities.{cap_id}]")
  print('description = "TODO: what this scenario verifies"')
  print('status = "unverified"')
  print("platforms = []")
  print(f'scenario_file = "{name}.py"')
  ```

- `tools/capabilities.py:51-58` — `scenarios_for_platform` filters
  `if platform in cap.get("platforms", [])`; `scenario_sim_configs`
  (`:61-81`) filters identically.
- `tasks.py:263-270` — `_resolve_scenario_config` delegates to
  `scenario_sim_configs("sim")`, so a `platforms = []` entry returns `None`.
- `tasks.py:996-1002` — `scenario` command on `None` config:

  ```python
  cfg = _resolve_scenario_config(name)
  if cfg is None:
      _resolve_scenario_script(name)
      print(
          f"No declared sim config for '{name}' in tests/capabilities.toml — "
          "running against the existing sim (start one with `just sim` first)."
      )
  ```

- `tools/capabilities.py:38-48` — `mark` sets `status = "verified"` and adds
  the platform; it is the only writer of `status`.
- Every existing entry in `tests/capabilities.toml` already has
  `platforms = ["sim"]` and `status = "verified"` — nothing to migrate.

## Commands you will need

| Purpose | Command | Expected |
|---------|---------|----------|
| Quality gate | `just check` | exit 0 |
| Targeted tests | `uv run pytest tests/unit/test_capabilities.py tests/unit/test_scenario_sim_config.py tests/unit/test_scenario_scaffold.py -q` | all pass |
| Scaffold smoke | `uv run tasks.py scenario-new 99_smoke_test` | prints snippet with `platforms = ["sim"]` |

## Scope

**In scope**:
- `tasks.py` (`scenario_new` print block; the `scenario` command's `cfg is None` message)
- `tests/unit/test_scenario_scaffold.py` (extend)
- `AGENTS.md` — the scenario-authoring note (one sentence: `platforms` = intent, `status` = verification via `cap mark`)

**Out of scope**:
- `tools/capabilities.py` — the filter semantics are now correct BY the
  decision above; do not add a second resolution path that ignores `platforms`
- `tools/scenario_scaffold.py` (the stub template itself is fine)
- `tests/capabilities.toml` (no migration needed)

## Git workflow

- Branch: `advisor/052-scaffold-declared-sim`
- Commit style: `fix(dx): scaffolded scenarios declare platforms=["sim"] so their sim config resolves`

## Steps

### Step 1: Fix the printed snippet

In `tasks.py` `scenario_new`, change `print("platforms = []")` to
`print('platforms = ["sim"]')`. Immediately after the snippet block, add one
explanatory line:

```python
print("   (platforms declares where it runs; `just cap mark` records verification)")
```

**Verify**: `uv run tasks.py scenario-new 99_smoke_test` → output contains
`platforms = ["sim"]`; then delete the created file
`tests/scenarios/99_smoke_test.py` (it must NOT be committed).

### Step 2: Make the no-config fallback message actionable

In the `scenario` command (`tasks.py:999-1002`), extend the message so the
agent learns the fix, not just the symptom:

```
No declared sim config for '<name>' in tests/capabilities.toml — running
against the existing sim. To make `just scenario <name>` boot the right sim,
add the entry with platforms = ["sim"] (see `just scenario-new` output).
```

**Verify**: `just check` → exit 0.

### Step 3: Tests

Extend `tests/unit/test_scenario_scaffold.py` (3 tests exist; follow their
style — they call `render_scenario`/`class_name` directly). The snippet is
printed by `tasks.py`, not the scaffold lib, so test at the right seam: add a
test that runs `scenario_new` via typer's `CliRunner` (see
`tests/unit/test_mission_cli.py` for the established CliRunner pattern in this
repo) against a `tmp_path`-redirected target, asserting the output contains
`platforms = ["sim"]` and NOT `platforms = []`. If `scenario_new`'s target dir
is not parameterizable, monkeypatch `tasks.ROOT` — and if THAT proves tangled,
fall back to asserting on the literal source line:
`'platforms = [\"sim\"]' in Path("tasks.py").read_text()` with a comment (an
honest pin is better than a skipped test).

**Verify**: `uv run pytest tests/unit/ -q` → all pass.

### Step 4: Document the two-field contract

In `AGENTS.md`, "Code changes" section, the new-scenario bullet (currently
says "Add a capability entry in `tests/capabilities.toml`") — extend with:
`platforms = ["sim"]` declares intent (enables `just scenario`/e2e); `status`
stays `"unverified"` until `just cap mark <id> sim` after a PASS.

**Verify**: `just check` → exit 0 (the docs checker validates AGENTS.md tokens).

## Done criteria

- [ ] `uv run tasks.py scenario-new 99_x && rm tests/scenarios/99_x.py` prints `platforms = ["sim"]`
- [ ] New unit test covering the snippet passes; full suite green (`just check` exit 0)
- [ ] AGENTS.md documents platforms-vs-status
- [ ] `grep -n 'platforms = \[\]' tasks.py` → no matches
- [ ] `plans/README.md` row updated

## STOP conditions

- `scenario_sim_configs` or `scenarios_for_platform` gained additional
  callers that treat `platforms` as "verified platforms" (grep both names) —
  the intent/verification split would then change behavior beyond this plan.
- Plan 053 landed first and already changed these exact lines — reconcile
  instead of overwriting.

## Maintenance notes

- Plan 053 (e2e roster enforcement) assumes "declared in capabilities.toml
  with platforms=[\"sim\"] ⇒ runs in e2e"; this plan is what makes that
  assumption hold for new scenarios.
- Reviewer: confirm no change to `tools/capabilities.py` semantics — this
  plan is docs + scaffold output + message only.
