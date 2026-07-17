# Plan 070: e2e report integrity — a scenario that crashes before writing its report still shows up as a FAIL with a reason

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in "STOP conditions" occurs, stop and report — do not
> improvise. When done, update this plan's row in `plans/README.md` unless a
> reviewer told you they maintain the index.
>
> **Drift check (run first)**:
> `git diff --stat 6ce9aec..HEAD -- tasks.py tests/scenarios/_common.py tests/unit/test_tasks_e2e_groups.py tools/log_summary.py`
> On any mismatch with the "Current state" excerpts below, STOP.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none (edits `tasks.py`; land after 067/068 if they are in flight, to avoid merge noise — regions are disjoint)
- **Category**: bug / correctness
- **Planned at**: commit `6ce9aec`, 2026-07-16

## Why this matters

The e2e cycle's per-scenario truth lives in `logs/scenario_<name>.json`,
written by `write_report` in `tests/scenarios/_common.py`. The `Scenario`
base class writes a report on every *Python-level* exit path — but nothing
protects against the process dying before that code runs: a segfault in
rclpy/DDS, an `ImportError` at module load, an OOM kill, or a `kill -9`. In
those cases the e2e loop in `tasks.py` counts the nonzero exit code as a fail
(correct), but the report block and `just log summary` read the scenario
JSONs — and either omit the scenario entirely or, worse, read a **stale JSON
from a previous run** and display an old PASS next to a failed cycle. The
agent-facing contract ("a silently-dead stack reports NOT READY, never a
false pass") is violated exactly when debugging is hardest.

There is also the inverse hole: a scenario process that exits **0** without
writing a fresh report (a stub, a bad refactor of `run_main`) is currently
counted as a silent pass with no evidence on disk.

The group-level version of this fix already exists: when the sim never
becomes ready, `_run_e2e_sim_group` synthesizes a failure JSON per scenario
(`tasks.py:986–1006`) precisely "so the e2e report block lists them instead
of silently omitting scenarios that never ran". This plan extends the same
guarantee to the per-scenario level.

## Current state

- `tasks.py` `_run_e2e_sim_group` (lines 913–1032). The scenario loop
  (lines 1008–1014):

  ```python
  for s in scenarios:
      print(f"Running scenario {s}...")
      res_s = subprocess.run(
          ["uv", "run", "python", f"tests/scenarios/{s}.py"], cwd=str(ROOT)
      )
      if res_s.returncode != 0:
          fails += 1
  ```

  No check that `logs/scenario_{s}.json` exists or is fresh.
- The existing group-level synthesis (lines 986–1006), the pattern to mirror:

  ```python
  # Write a failure report per scenario (same shape as write_report in
  # tests/scenarios/_common.py) so the e2e report block lists them
  # instead of silently omitting scenarios that never ran.
  for s in scenarios:
      (LOG_DIR / f"scenario_{s}.json").write_text(
          json.dumps(
              {
                  "scenario": s,
                  "passed": False,
                  "elapsed_s": 0.0,
                  "detail": {
                      "reason": "sim_never_ready",
                      "vision": vision,
                      "overlay": overlay,
                      "model": model,
                      "world": world,
                  },
              },
              indent=2,
          )
          + "\n",
          encoding="utf-8",
      )
  ```

- `tests/scenarios/_common.py` `write_report` — the canonical report shape;
  top-level keys are exactly `scenario`, `passed`, `elapsed_s`, `detail`.
  Consumers: the e2e report block in `tasks.py`, `tools/log_summary.py`,
  `just scenario-status`. Do not add or rename top-level keys.
- `tests/unit/test_tasks_e2e_groups.py` — existing unit test importing
  directly from `tasks` (`from tasks import _e2e_sim_groups`); follow this
  import pattern for the new helper's tests.
- Scenario reports are keyed by name, not run id, so staleness must be
  detected by mtime against the moment the scenario subprocess started.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Quality gate | `just check` | exit 0 |
| Targeted tests | `uv run pytest tests/unit/test_tasks_e2e_groups.py -q` | all pass |
| Full e2e (optional live gate) | `just test e2e` | aggregate PASS, exit 0 |

## Scope

**In scope**:
- `tasks.py` (`_run_e2e_sim_group` scenario loop + one new pure helper)
- `tests/unit/test_tasks_e2e_groups.py`

**Out of scope** (do NOT touch):
- `tests/scenarios/_common.py` — `write_report` and the `Scenario` base are
  correct; the hole is at the supervisor level, not the scenario level.
- The `sim_never_ready` block itself (keep it; the new helper may be reused
  by it only if the refactor is a pure extraction with identical output).
- `tools/log_summary.py`, `tools/scenario_status.py` — they consume the same
  JSON shape and need no change.

## Git workflow

- Branch: `advisor/070-e2e-report-integrity`
- Commit style: `fix(e2e): synthesize a failure report when a scenario dies or exits without writing one`
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Extract a pure fallback-report helper

Add to `tasks.py` (near `_run_e2e_sim_group`), a pure function so it is
unit-testable without subprocesses:

```python
def _fallback_scenario_report(scenario: str, reason: str, config: dict[str, str]) -> str:
    """JSON text for a scenario that produced no fresh report of its own.

    Same shape as ``write_report`` in tests/scenarios/_common.py so every
    consumer (e2e report block, log summary, scenario-status) reads it
    unchanged.
    """
    return (
        json.dumps(
            {
                "scenario": scenario,
                "passed": False,
                "elapsed_s": 0.0,
                "detail": {"reason": reason, **config},
            },
            indent=2,
        )
        + "\n"
    )
```

Refactor the existing `sim_never_ready` block (lines 986–1006) to call it:
`(LOG_DIR / f"scenario_{s}.json").write_text(_fallback_scenario_report(s,
"sim_never_ready", {"vision": vision, "overlay": overlay, "model": model,
"world": world}), encoding="utf-8")`. The written bytes must be identical to
before (same key order, `indent=2`, trailing newline).

**Verify**: `uv run pytest tests/unit/test_tasks_e2e_groups.py -q` → existing
test passes. Byte-equivalence spot check:
`uv run python -c "from tasks import _fallback_scenario_report; print(_fallback_scenario_report('01_arm_takeoff','sim_never_ready',{'vision':'none','overlay':'auto_arm','model':'x500','world':'default'}))"`
→ output matches the old inline JSON (keys in order scenario, passed,
elapsed_s, detail; detail starts with reason).

### Step 2: Freshness check after each scenario subprocess

Rewrite the scenario loop (lines 1008–1014) to:

```python
for s in scenarios:
    print(f"Running scenario {s}...")
    report = LOG_DIR / f"scenario_{s}.json"
    started_at = _time.time()
    res_s = subprocess.run(
        ["uv", "run", "python", f"tests/scenarios/{s}.py"], cwd=str(ROOT)
    )
    fresh = report.exists() and report.stat().st_mtime >= started_at
    if res_s.returncode != 0:
        fails += 1
        if not fresh:
            print(
                f"  [FAIL] {s} exited {res_s.returncode} without writing a report; "
                "synthesizing crashed_before_report",
                file=sys.stderr,
            )
            report.write_text(
                _fallback_scenario_report(
                    s,
                    "crashed_before_report",
                    {"vision": vision, "overlay": overlay, "model": model, "world": world},
                ),
                encoding="utf-8",
            )
    elif not fresh:
        # Exit 0 but no fresh report: never trust it as a pass.
        fails += 1
        print(
            f"  [FAIL] {s} exited 0 but wrote no report; counting as FAIL",
            file=sys.stderr,
        )
        report.write_text(
            _fallback_scenario_report(
                s,
                "no_report_written",
                {"vision": vision, "overlay": overlay, "model": model, "world": world},
            ),
            encoding="utf-8",
        )
```

Notes:
- `_time` is already imported in `tasks.py` (`import time as _time`) — verify
  with `rg -n "import time" tasks.py` and match whatever alias exists.
- Use wall-clock `time.time()` (not monotonic) because it is compared to a
  filesystem mtime.
- A subsecond-mtime filesystem edge (mtime granularity 1s making a fresh
  report look stale) is avoided by `>=` on `started_at`; if the target
  filesystem truncates mtimes, subtract 1s from `started_at` in the
  comparison and note it in a comment.

**Verify**: manual fault injection without a sim —
1. `uv run python - <<'EOF'` creating a fake stale report:
   `from pathlib import Path; import json, os, time; p=Path('logs/scenario_zz_fake.json'); p.write_text(json.dumps({"scenario":"zz_fake","passed":True,"elapsed_s":1.0,"detail":{}})); os.utime(p, (time.time()-3600,)*2)` `EOF`
2. In a python REPL, simulate the loop body against a subprocess
   `["python", "-c", "import sys; sys.exit(1)"]` with `s="zz_fake"` and
   confirm the file is overwritten with `"reason": "crashed_before_report"`
   and `"passed": false`.
3. Delete `logs/scenario_zz_fake.json` afterwards.

### Step 3: Unit tests

Add to `tests/unit/test_tasks_e2e_groups.py` (same import style):

```python
from tasks import _fallback_scenario_report
```

- `test_fallback_report_matches_write_report_shape`: `json.loads` the helper
  output; assert `set(d) == {"scenario", "passed", "elapsed_s", "detail"}`,
  `d["passed"] is False`, `d["detail"]["reason"] == "crashed_before_report"`,
  and the config keys are present in `detail`.
- `test_fallback_report_is_valid_for_scenario_status`: assert the text ends
  with `"\n"` and round-trips through `json.loads` (guards the `+ "\n"` and
  `indent=2` contract that `just scenario-status` and `log summary` parse).

**Verify**: `uv run pytest tests/unit/test_tasks_e2e_groups.py -q` → all pass.

### Step 4: Full gate

**Verify**: `just check` → exit 0.

Optional live gate (recommended if a sim-capable machine is at hand):
`just test e2e` → 8/8 PASS, and `rg crashed_before_report logs/` → no matches
(the healthy path never triggers the fallback).

## Test plan

- The two unit tests in step 3 pin the JSON shape against
  `write_report`'s consumers.
- Step 2's manual fault injection demonstrates both new paths
  (`crashed_before_report`, stale-report-not-trusted).
- Existing `test_e2e_sim_groups_isolates_scenarios_with_same_config` stays
  green (grouping logic untouched).

## Done criteria

- [ ] `uv run pytest tests/unit/test_tasks_e2e_groups.py -q` → all pass
- [ ] `rg -n "crashed_before_report|no_report_written" tasks.py` → both reasons present in the scenario loop
- [ ] The `sim_never_ready` block now calls `_fallback_scenario_report` and its output is byte-identical to before
- [ ] A scenario subprocess that exits 0 without a fresh report is counted in `fails`
- [ ] `just check` → exit 0
- [ ] `plans/README.md` status row updated

## STOP conditions

- `write_report` in `tests/scenarios/_common.py` turns out to have a
  different top-level key set than `{scenario, passed, elapsed_s, detail}` —
  re-read it and mirror what is actually there; do not invent keys.
- Any consumer (`tools/log_summary.py`, `tools/scenario_status.py`, the e2e
  report block) fails to parse the synthesized JSON — fix the synthesis, not
  the consumer.
- The refactored `sim_never_ready` block's output differs byte-wise from the
  current inline version.

## Maintenance notes

- If a new scenario supervisor is ever added (e.g. hardware e2e), it must
  reuse `_fallback_scenario_report` — the invariant is "every scheduled
  scenario has a fresh report JSON after the run, pass or fail, no
  exceptions".
- The reasons are part of the agent-facing vocabulary: `sim_never_ready`
  (group boot failed), `crashed_before_report` (process died mid-scenario),
  `no_report_written` (exit 0 without evidence). Keep them stable; logs and
  memory reference them.
