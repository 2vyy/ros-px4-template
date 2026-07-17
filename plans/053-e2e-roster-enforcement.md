# Plan 053: e2e enforces the scenario roster (no scenario can silently not run)

> **Executor instructions**: Follow this plan step by step, verifying each
> step. On any STOP condition, stop and report. When done, update
> `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 01f94c7..HEAD -- tasks.py tools/e2e_report.py tools/capabilities.py tests/unit/test_e2e_report.py tests/unit/test_capabilities.py`
> On any mismatch with the excerpts below, STOP.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none (pairs with plan 052)
- **Category**: tests
- **Planned at**: commit `01f94c7`, 2026-07-10

## Why this matters

`just test e2e` promises "every declared capability verified", but there are
two silent-skip holes:

1. **Undeclared file**: a scenario file added to `tests/scenarios/` without a
   `tests/capabilities.toml` entry never runs anywhere — e2e iterates only
   declared configs, `just check` runs only unit tests. Green pipeline,
   unverified capability.
2. **Missing report**: a sim group that never becomes ready produces **no**
   `logs/scenario_<name>.json` for its scenarios, so the printed e2e report
   block shows only the scenarios that did run — all-PASS rows on a failing
   run. (The exit code is correct via the `fails` counter; the human/agent-
   facing report contradicts it.)

Also: an empty roster only warns (`Warning: no sim scenarios found`) and
proceeds to a vacuous success.

## Current state

- `tasks.py:934-936`:

  ```python
  configs = scenario_sim_configs("sim")
  if not configs:
      print("Warning: no sim scenarios found in capabilities.toml")
  ```

- `tasks.py:844-850` (`_run_e2e_sim_group`) — readiness failure returns
  `len(scenarios)` as fails but writes no per-scenario JSON:

  ```python
  except subprocess.CalledProcessError:
      print(f"  [FAIL] sim never became ready; failing {len(scenarios)} scenario(s) ...")
      return len(scenarios)
  ```

- `tools/e2e_report.py:27-47` — `build_block` globs `scenario_*.json`; a
  scenario with no file is invisible; only the zero-files case fails.
- Scenario reports are written by `tests/scenarios/_common.py:write_report`
  (`:106-123`) with shape
  `{"scenario", "passed", "elapsed_s", "detail": {...}}`.
- Roster sources: files `tests/scenarios/[0-9][0-9]_*.py` (see the glob in
  `tests/unit/test_scenario_imports.py:11`) vs. declarations
  `tools/capabilities.py:scenarios_for_platform` (`:51-58`). No test
  cross-checks them (verified: `test_capabilities.py` builds synthetic TOML
  only; `test_scenario_imports.py` only imports files).
- Exit codes: `tools/cli_verdict.py` `ExitCode` — OK=0, FAIL=1, USAGE=2,
  PRECONDITION=3. An empty roster is a precondition failure (3).

## Commands you will need

| Purpose | Command | Expected |
|---------|---------|----------|
| Quality gate | `just check` | exit 0 |
| Targeted tests | `uv run pytest tests/unit/test_e2e_report.py tests/unit/test_capabilities.py tests/unit/test_scenario_roster.py -q` | all pass |
| Full e2e (operator/distrobox) | `just test e2e` | all PASS, exit 0 |

## Scope

**In scope**:
- `tasks.py` (`_run_e2e_sim_group` readiness-fail path; empty-roster handling in `test e2e`)
- `tools/e2e_report.py` (optional roster argument — see Step 3)
- `tests/unit/test_scenario_roster.py` (new)
- `tests/unit/test_e2e_report.py` (extend)

**Out of scope**:
- `tests/scenarios/*` and `tests/capabilities.toml` — currently consistent
  (7 files, 7 entries); the new test enforces it stays so
- `tools/capabilities.py` — read-only consumer here
- The scenario-number gap `04` — known-cosmetic, deliberately not an error
  (the roster check compares SETS, not numbering)

## Git workflow

- Branch: `advisor/053-e2e-roster-enforcement`
- Commit style: `fix(e2e): enforce scenario roster; report never-ran scenarios; fail empty roster`

## Steps

### Step 1: Unit test — every scenario file declared, every declaration has a file

Create `tests/unit/test_scenario_roster.py`:

```python
"""The scenario roster: files in tests/scenarios/ <-> declarations in capabilities.toml."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from capabilities import scenarios_for_platform  # noqa: E402


def test_every_scenario_file_is_declared_for_sim() -> None:
    files = {p.stem for p in (ROOT / "tests" / "scenarios").glob("[0-9][0-9]_*.py")}
    declared = set(scenarios_for_platform("sim"))
    assert files - declared == set(), (
        f"scenario files not declared in tests/capabilities.toml (platforms must "
        f"include 'sim'): {sorted(files - declared)}"
    )


def test_every_declared_scenario_has_a_file() -> None:
    files = {p.stem for p in (ROOT / "tests" / "scenarios").glob("[0-9][0-9]_*.py")}
    declared = set(scenarios_for_platform("sim"))
    assert declared - files == set(), (
        f"capabilities.toml declares scenarios with no file: {sorted(declared - files)}"
    )
```

Check the tools-import convention first: `tests/unit/test_check_topics.py` or
`tests/conftest.py` show how existing tests import from `tools/` — match it
(there may already be a conftest path hook making the `sys.path` dance
unnecessary).

**Verify**: `uv run pytest tests/unit/test_scenario_roster.py -q` → 2 passed.
Kill-test: temporarily create `tests/scenarios/98_orphan.py` (`touch`), rerun →
first test FAILS naming `98_orphan`; delete the file; rerun → passes.

### Step 2: Never-ready groups write failure reports

In `tasks.py` `_run_e2e_sim_group`'s readiness `except` block, before
`return len(scenarios)`, write one JSON per scenario in the group, matching
`write_report`'s shape exactly:

```python
for s in scenarios:
    (LOG_DIR / f"scenario_{s}.json").write_text(
        json.dumps(
            {
                "scenario": s,
                "passed": False,
                "elapsed_s": 0.0,
                "detail": {"reason": "sim_never_ready", "vision": vision, "overlay": overlay},
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
```

(`json` is already imported in tasks.py; check, else import it.)

**Verify**: `uv run pytest tests/unit/test_e2e_report.py -q` → passes; then
extend `test_e2e_report.py` with a case: a report dir containing one passing
file and one `sim_never_ready` file → `build_block` returns FAIL code and the
block text contains `sim_never_ready` (follow the existing tmp_path fixtures
in that file).

### Step 3: Empty roster is a precondition failure

In `tasks.py` `test e2e` (`:934-936`), replace the warning with:

```python
if not configs:
    print(
        "No sim scenarios declared in tests/capabilities.toml (platforms must "
        "include 'sim'). Refusing to report a vacuous e2e pass.",
        file=sys.stderr,
    )
    raise typer.Exit(int(ExitCode.PRECONDITION))
```

**Verify**: `just check` → exit 0 (the roster test from Step 1 guards the
real registry, so the suite still passes).

### Step 4: Full-gate live run (operator/distrobox)

`just test e2e` → all 7 scenarios PASS, exit 0, and the report block lists
exactly 7 rows.

## Done criteria

- [ ] `tests/unit/test_scenario_roster.py` exists, 2 tests pass; kill-test demonstrated
- [ ] Never-ready path writes `scenario_<name>.json` with `reason: sim_never_ready` (unit-tested via `build_block`)
- [ ] Empty roster exits 3, not 0
- [ ] `just check` exit 0; `just test e2e` all PASS (operator)
- [ ] `plans/README.md` row updated

## STOP conditions

- The roster test fails on the CURRENT tree (a genuine orphan exists at
  execution time) — fix-forward is out of scope; report which scenario is
  orphaned and let the owner decide declare-vs-delete.
- `write_report`'s JSON shape differs from the excerpt (drift) — match the
  live shape, and if it has diverged structurally, STOP.

## Maintenance notes

- Plan 052 makes newly scaffolded scenarios declare `platforms = ["sim"]`;
  together these plans close the "new scenario silently unverified" hole.
- If a future scenario is legitimately hardware-only, declare it with
  `platforms = ["hw"]` — the roster test only checks the sim direction
  files→declared; extend it then, not now.
