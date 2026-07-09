# Plan 018: The e2e gate fails when the topic audit or report fails

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving on. If
> anything in "STOP conditions" occurs, stop and report — do not improvise. When
> done, update this plan's row in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 0f93f0e..HEAD -- tasks.py tools/e2e_report.py tools/check_topics.py`
> If any changed, compare the "Current state" excerpts to the live code before
> proceeding; on a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: correctness
- **Planned at**: commit `0f93f0e`, 2026-06-22

## Why this matters

`just test e2e` is the headless end-to-end gate this template exists to provide —
the thing an agent or CI trusts to say "the stack works." But two of its checks
have their exit codes silently dropped:

1. The **topic-graph audit** (`tools/check_topics.py`, the interface-drift guard
   that enforces `docs/TOPICS.md`) is run without `check=` and its return code is
   never inspected. A live graph that violates the manifest does **not** fail
   e2e.
2. The **e2e report** (`tools/e2e_report.py`) exits 1 when no scenarios ran or a
   result is malformed, but that exit code is ignored too.

So `just test e2e` can print "E2E cycle finished successfully (all scenarios
passed)" while topics are missing/mistyped, or while zero scenarios actually ran.
A green gate that can be wrong is worse than no gate. This plan makes both
failures count toward the e2e exit code. It is a small, well-contained change to
the orchestrator with a clean unit-test story for the report path.

## Current state

In `tasks.py`, `_run_e2e_sim_group(...)` runs the topic audit but ignores the
result (`tasks.py:754-759`):
```python
        if audit_topics:
            print("Auditing topic graph...")
            subprocess.run(
                ["uv", "run", "python", "tools/check_topics.py", "--manifest", "docs/TOPICS.md"],
                cwd=str(ROOT),
            )
```
The function returns `fails` (count of failed scenarios) — a nonzero topic audit
never increments it.

In the `e2e` command body, the report is run and its exit code ignored
(`tasks.py:851-859`):
```python
            print("Summarizing execution log...")
            _summarize_logs_silent()

            print("Generating E2E Report...")
            subprocess.run(["uv", "run", "python", "tools/e2e_report.py"], cwd=str(ROOT))

            if fails > 0:
                raise typer.Exit(int(ExitCode.FAIL))
            print("E2E cycle finished successfully (all scenarios passed).")
```

`tools/e2e_report.py` already exits with the right code (`build_block` returns
`(block, code)`; `main()` does `sys.exit(code)`), where code is `FAIL` when no
scenarios ran or any scenario failed. `build_block` is a pure function
(`tools/e2e_report.py:27-47`) — directly unit-testable.

`check_topics.py` exits nonzero when the live topic graph violates the manifest
(it is the tool behind `just log topics`).

The `ExitCode` enum (`tools/cli_verdict.py:16-22`): `OK=0`, `FAIL=1`, `USAGE=2`,
`PRECONDITION=3`.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Run report unit tests | `uv run pytest tests/unit/test_e2e_report.py -q` | all pass |
| Run full unit suite | `uv run pytest tests/unit/ -q` | all pass |
| Lint | `uv run ruff check tools/e2e_report.py tests/unit/test_e2e_report.py` | exit 0 |
| Typecheck | `uv run ty check tools/ tests/unit` | exit 0 |
| Inspect e2e wiring | `grep -n "check_topics\|e2e_report\|return fails\|audit_topics" tasks.py` | shows the edited lines |

A full `just test e2e` run needs a working sim (Gazebo/PX4/distrobox) and is the
operator's sign-off, not an executor gate — see STOP conditions. The unit-level
verification below fully covers the report-path logic; the topic-audit wiring is
verified by reading the diff.

## Scope

**In scope**:
- `tasks.py` — `_run_e2e_sim_group` (count the topic-audit failure) and the
  `e2e` command body (fail on the report's nonzero exit).
- `tests/unit/test_e2e_report.py` — add a regression test for the
  no-scenarios-ran path if one is not already present.

**Out of scope** (do NOT touch):
- `tools/check_topics.py` — already exits correctly; do not change it.
- `tools/e2e_report.py` — already exits correctly; do not change its logic. (You
  may read it to write tests.)
- The `scenario` command and `_run_e2e_sim_group`'s scenario-running loop — they
  already count `fails` correctly.
- The single-`scenario`/`sim`/`hw` commands — unaffected.

## Git workflow

- Branch: `advisor/018-e2e-propagate-exit-codes`
- Conventional commits (e.g.
  `fix(e2e): fail the gate when the topic audit or report fails`).
- Do NOT push or open a PR unless instructed.

## Steps

### Step 1: Count the topic-audit failure in `_run_e2e_sim_group`

Change the audit block (`tasks.py:754-759`) so a nonzero return increments
`fails`. Target:
```python
        if audit_topics:
            print("Auditing topic graph...")
            res_topics = subprocess.run(
                ["uv", "run", "python", "tools/check_topics.py", "--manifest", "docs/TOPICS.md"],
                cwd=str(ROOT),
            )
            if res_topics.returncode != 0:
                print("  [FAIL] topic graph violates docs/TOPICS.md", file=sys.stderr)
                fails += 1
```
`fails` is already the function's running counter and return value, so this makes
a topic violation count as a failure for the group (and thus for the whole e2e
exit code, since the caller sums group `fails`).

**Verify**: `grep -n "res_topics" tasks.py` → shows the new return-code check;
the function still ends with `return fails`.

### Step 2: Fail the e2e command on a nonzero report exit

Change the report invocation (`tasks.py:854-855`) to capture and honor the exit
code. Target:
```python
            print("Generating E2E Report...")
            res_report = subprocess.run(
                ["uv", "run", "python", "tools/e2e_report.py"], cwd=str(ROOT)
            )

            if fails > 0 or res_report.returncode != 0:
                raise typer.Exit(int(ExitCode.FAIL))
            print("E2E cycle finished successfully (all scenarios passed).")
```
This catches the "no scenarios ran" and malformed-result cases that `fails`
alone misses.

**Verify**: `grep -n "res_report" tasks.py` → shows the capture and the combined
`if fails > 0 or res_report.returncode != 0:` guard.

### Step 3: Add a regression unit test for the report's failure path

In `tests/unit/test_e2e_report.py`, ensure there is a test asserting that
`build_block` returns a `FAIL` exit code when the log dir has **no**
`scenario_*.json` files (the "no scenarios ran" case), and `OK` when all present
scenarios passed. If such tests already exist, add only what is missing. Use a
`tmp_path` directory; write `scenario_*.json` files matching the shape
`e2e_report.py` reads (`{"scenario": str, "passed": bool, "detail": {...},
"elapsed_s": float}`). Example skeleton:
```python
import json
from pathlib import Path
from e2e_report import build_block
from cli_verdict import ExitCode

def test_no_scenarios_is_fail(tmp_path: Path) -> None:
    _, code = build_block(tmp_path)
    assert code == int(ExitCode.FAIL)

def test_all_passed_is_ok(tmp_path: Path) -> None:
    (tmp_path / "scenario_x.json").write_text(
        json.dumps({"scenario": "x", "passed": True, "detail": {}, "elapsed_s": 1.0})
    )
    _, code = build_block(tmp_path)
    assert code == int(ExitCode.OK)

def test_one_failed_is_fail(tmp_path: Path) -> None:
    (tmp_path / "scenario_y.json").write_text(
        json.dumps({"scenario": "y", "passed": False, "detail": {"reason": "timeout"}, "elapsed_s": 2.0})
    )
    _, code = build_block(tmp_path)
    assert code == int(ExitCode.FAIL)
```
(`e2e_report` and `cli_verdict` are importable because `tests/conftest.py` puts
`tools/` on `sys.path`.)

**Verify**: `uv run pytest tests/unit/test_e2e_report.py -q` → all pass.

## Test plan

- Add/confirm the three `build_block` cases above in
  `tests/unit/test_e2e_report.py` (no-scenarios → FAIL, all-pass → OK,
  one-fail → FAIL).
- The topic-audit wiring (Step 1) has no pure-function seam to unit-test without
  a live graph; it is verified by code review of the diff plus the operator's
  next real `just test e2e`. Note this explicitly in the PR description.
- Verification: `uv run pytest tests/unit/ -q` → all pass.

## Done criteria

ALL must hold:

- [ ] `grep -n "res_topics" tasks.py` shows the topic-audit return code incrementing `fails`
- [ ] `grep -n "res_report" tasks.py` shows the report return code gating the success message
- [ ] `uv run pytest tests/unit/test_e2e_report.py -q` passes, including a no-scenarios-ran FAIL case
- [ ] `uv run pytest tests/unit/ -q` exits 0 (no regressions)
- [ ] `uv run ruff check tasks.py tools/e2e_report.py tests/unit/test_e2e_report.py` exits 0
- [ ] Only the in-scope files are modified
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report if:

- `tasks.py:754-759` or `tasks.py:851-859` does not match "Current state" (the
  orchestrator drifted).
- `_run_e2e_sim_group` no longer returns `fails`, or the `e2e` command no longer
  computes `fails` the same way (the failure-counting model changed) — adapt only
  after confirming the new model with the operator.
- A full `just test e2e` is unavailable to you (no sim/distrobox). That is fine —
  do NOT attempt to stand up Gazebo/PX4 to "prove" the topic path. Finish the
  unit-verified report path, mark the topic-audit change as review-verified, and
  hand the live e2e sign-off to the operator.

## Maintenance notes

- If more post-scenario audits are added to the e2e flow later (e.g. a log-arc
  sanity check), wire their exit codes into `fails` / the final guard the same
  way — the principle is "every gate that can fail must be able to fail the run."
- Reviewer: confirm the success message ("all scenarios passed") is now
  unreachable when either the topic audit or the report failed.
