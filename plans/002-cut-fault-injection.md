# Plan 002: Remove the unexercised fault-injection subsystem

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 5175284..HEAD -- tools/fault_inject.py src/core/ros_px4_template_core/lib/fault_transforms.py tests/unit/test_fault_transforms.py`
> If any in-scope file changed since this plan was written, compare the
> "Current state" facts against the live code before proceeding; on a mismatch,
> treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: tech-debt
- **Planned at**: commit `5175284`, 2026-06-20

## Why this matters

This template is built for unattended, e2e CLI agent work: the value
proposition is that every capability is *exercised* by the scenario/e2e harness.
The fault-injection subsystem (`tools/fault_inject.py` plus its support library
and test, ~250 LOC) is the one piece that breaks that promise. Nothing runs it:
no `just` recipe, no scenario, no `capabilities.toml` entry, no other importer.
It is a manual-only utility that gestures at robustness testing the harness
never performs. Half-built tooling in a template is worse than none — people who
clone it inherit code they assume is load-bearing. Cutting it makes the template
honest about what it actually verifies. (The maintainer chose "cut it" over
wiring a fault scenario.)

## Current state

Three files form a closed, unreachable loop:

- `tools/fault_inject.py` (141 lines) — a standalone `rclpy` node, run only by
  hand: `uv run tools/fault_inject.py --fault gps_dropout --duration 5`. It
  imports `ros_px4_template_core.lib.fault_transforms`.
- `src/core/ros_px4_template_core/lib/fault_transforms.py` (36 lines) — pure
  transform helpers (`apply_altitude_spike`, etc.). Its module docstring says
  "The caller (tools/fault_inject.py) is responsible for subscribing/publishing"
  — i.e. its only consumer is the orphan tool.
- `tests/unit/test_fault_transforms.py` — unit test for the above.

Reachability checks (all run during planning, expected to still hold):
- `rg -l "fault_inject" tasks.py justfile tests/scenarios tests/capabilities.toml` → **no matches** (not wired anywhere).
- `rg -n "fault" src/core/setup.py` → **no matches** (not a console entry point).
- `rg -rln "fault_transforms" src tests tools` → only the three files above
  (plus `__pycache__`/`.ruff_cache` artifacts, which are not tracked).
- `rg -n "fault" tools/check_invariants.py tests/conftest.py` → **no matches**.

`just check` runs `ty` and `pytest` over `tools/` and `tests/unit/`, and `ruff`
over `tools`/`tests`. Deleting these files removes them from those scopes
cleanly; there are no importers left to break.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Confirm no importers remain | `rg -rln "fault_transforms\|fault_inject" src tools tests --glob '!**/__pycache__/**'` | no matches after deletion |
| Unit tests | `just test` | exits 0, all pass |
| Full quality gate | `just check` | exits 0, `all checks passed.` |

## Scope

**In scope** (delete these files):
- `tools/fault_inject.py`
- `src/core/ros_px4_template_core/lib/fault_transforms.py`
- `tests/unit/test_fault_transforms.py`
- `plans/README.md` (status row only)

**Out of scope** (do NOT touch):
- Any other file in `tools/`, `src/`, or `tests/`. No other module imports the
  deleted ones, so no edits are needed elsewhere. If you find one that does,
  that is a STOP condition.
- `docs/BACKLOG.md` or `docs/` — do not add or remove doc entries in this plan.
- The `mission_profile.py` dead-code item (a separate, deferred finding).

## Git workflow

- Branch: `advisor/002-cut-fault-injection`
- Commit style: conventional commits. Suggested message:
  `refactor: remove unexercised fault-injection subsystem`.
- Use `git rm` so the deletions are staged. Do NOT push or open a PR unless the
  operator instructed it.

## Steps

### Step 1: Confirm nothing imports the subsystem (pre-flight)

Before deleting, re-verify there are no consumers other than the three files:

```bash
rg -rln "fault_transforms|fault_inject" src tools tests --glob '!**/__pycache__/**'
```

**Verify**: output lists **only** `tools/fault_inject.py`,
`src/core/ros_px4_template_core/lib/fault_transforms.py`, and
`tests/unit/test_fault_transforms.py`. If any other file appears, **STOP** —
something now depends on this code and the cut is no longer safe.

### Step 2: Delete the three files

```bash
git rm tools/fault_inject.py \
       src/core/ros_px4_template_core/lib/fault_transforms.py \
       tests/unit/test_fault_transforms.py
```

**Verify**: `rg -rln "fault_transforms|fault_inject" src tools tests --glob '!**/__pycache__/**'` → no matches.

### Step 3: Run the unit suite and quality gate

The deleted test is gone; the remaining suite must still pass and the gate must
stay green (no dangling imports, no lint/type errors).

**Verify**:
- `just test` → exits 0, all pass.
- `just check` → exits 0, ends with `all checks passed.`

## Test plan

No new tests. This is a deletion; correctness is proven by the remaining suite
passing (`just test`) and the quality gate (`just check`) staying green with the
three files gone. The grep gate in Step 2 proves no orphaned references remain.

## Done criteria

ALL must hold:

- [ ] The three files no longer exist (`git status` shows them deleted/staged)
- [ ] `rg -rln "fault_transforms|fault_inject" src tools tests --glob '!**/__pycache__/**'` returns no matches
- [ ] `just test` exits 0
- [ ] `just check` exits 0
- [ ] No files outside the in-scope list are modified
- [ ] `plans/README.md` status row for 002 updated

## STOP conditions

Stop and report back (do not improvise) if:

- Step 1 shows any importer outside the three in-scope files (the subsystem
  gained a consumer since this plan was written — it may no longer be dead).
- `tests/capabilities.toml` or any file in `tests/scenarios/` references a fault
  scenario (someone wired it after planning).
- `just check` or `just test` fails after deletion for a reason that traces back
  to the removed files (would indicate a hidden dependency the greps missed).

## Maintenance notes

- If robustness/fault testing is wanted later, the right shape for this template
  is a `tests/scenarios/NN_fault_*.py` plus a `capabilities.toml` entry, so the
  e2e harness exercises it every run — rebuild it that way rather than restoring
  a manual-only tool.
- A reviewer should confirm the deletion does not touch any node or launch file;
  the subsystem was never part of `hardware.launch.py` or `sim_full.launch.py`.
