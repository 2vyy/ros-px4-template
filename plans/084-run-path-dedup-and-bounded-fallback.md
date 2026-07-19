# Plan 084: One failure-recording path in the e2e group runner; `just run` is always bounded

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat d44126d..HEAD -- tasks.py tools/run_supervisor.py tools/log_view.py tests/unit/test_tasks_e2e_groups.py tests/unit/test_run_supervisor.py tests/unit/test_log_view.py`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MED
- **Depends on**: none
- **Category**: tech-debt (+ one correctness fix)
- **Planned at**: commit `d44126d`, 2026-07-18

## Why this matters

`_run_e2e_sim_group` in `tasks.py` is the single densest branch cluster in the
repo's #1 hotspot file (tasks.py: 139 branch statements). The "mark the claim
failed, synthesize a fallback report, bump the fail count" concept is
open-coded five times with slight variations, so every change to the failure
contract must be made in five places in lockstep. Separately, `just run` for a
scenario with no declared sim config silently violates its own documented
contract ("bounded; always leaves a run record"): it launches an **unbounded**
subprocess with no supervisor, no deadline, and no run record — the exact
wedge-an-agent failure mode the Round 8 run supervisor exists to prevent.
This plan collapses the duplication (≈10 branch statements removed) and
deletes the unbounded path.

## Current state

- `tasks.py` — the task runner. Relevant regions at commit `d44126d`:
  - `_run_e2e_sim_group` (`tasks.py:1198-1360`): after `wait_ready` fails, and
    in each of three post-run verdict arms, the same three-part sequence
    repeats:
    ```python
    # tasks.py:1210-1214 (and again at :1273-1276, :1298-1301, :1324-1327)
    if registry is not None and failed_claims is not None:
        from capabilities import claim_for_scenario
        failed_claims.add(claim_for_scenario(registry, s) or s)
    ```
    and the identical config dict is inlined five times:
    ```python
    # tasks.py:1220-1225 (and again at :1245-1250, :1287-1292, :1312-1317, :1336-1341)
    {
        "vision": vision,
        "overlay": overlay,
        "model": model,
        "world": world,
    },
    ```
    The three verdict arms are `if stuck is not None:` (`:1271`),
    `elif rc != 0:` (`:1296`), `elif not fresh:` (`:1321`); each does
    `fails += 1`, the claim-marking block, a `print(...)`, and a
    `_fallback_scenario_report` write (the first two only `if not fresh`,
    the third always — note `fresh` is False in that arm by definition, so
    all three in fact write exactly when `not fresh`).
  - The "next: just log events" hint is duplicated:
    ```python
    # tasks.py:1347-1353
    if stuck is not None or rc != 0 or not fresh:
        rec = json.loads(record_path.read_text(encoding="utf-8"))
        t_end = int(rec.get("t_end") or 0)
        print(
            f"next: just log events --run {record_path.stem} | "
            f'rg -C5 "t={t_end}\\." logs/latest.log'
        )
    ```
    ```python
    # tasks.py:1527-1533 (inside run_cmd)
    recs = run_supervisor.list_run_records(limit=1)
    if recs and recs[0].get("record"):
        t_end = int(recs[0].get("t_end") or 0)
        print(
            f"next: just log events --run {recs[0]['record']} | "
            f'rg -C5 "t={t_end}\\." logs/latest.log'
        )
    ```
  - `run_cmd` (`tasks.py:1479-1534`): docstring line 1484 says "bounded;
    always leaves a run record", but the no-declared-config fallback is:
    ```python
    # tasks.py:1495-1507
    if cfg is None:
        print(
            f"No declared sim config for '{name}' in tests/capabilities.toml — "
            "running against the existing sim (start one with `just sim start` first). "
            ...
        )
        print(f"Running scenario test: {name}...")
        try:
            result = subprocess.run(["uv", "run", "python", str(script)], cwd=str(ROOT))
            fails = 0 if result.returncode == 0 else 1
        finally:
            _summarize_logs_silent()
    ```
    — no `run_supervisor.supervise`, no timeout, no run record.
  - `e2e` (`tasks.py:1401-1406`): a hidden, deprecated `--wait` flag whose
    parameter is never read in the function body:
    ```python
    wait: bool = typer.Option(
        False,
        "--wait",
        hidden=True,
        help="Deprecated: e2e blocks by default; this flag is a no-op.",
    ),
    ```
- `tools/run_supervisor.py:209-234` — `supervise`'s poll loop re-implements
  the truncation-aware incremental log read that already exists as
  `read_since` in `tools/log_view.py:23-46`. The shared primitive is:
  stat size; `if size < offset: offset = 0` (log truncated by a new boot);
  `if size > offset: open/seek(offset)/read().splitlines()`.
- Conventions: tools in `tools/` are flat modules imported by `tasks.py` via
  a `sys.path` insert (see the import block at the top of `tasks.py`).
  English-verdict prints go to stderr for failures. Tests for tasks e2e
  grouping live in `tests/unit/test_tasks_e2e_groups.py`; supervisor tests in
  `tests/unit/test_run_supervisor.py`.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Full gate | `just check` (host without ROS: `distrobox enter ubuntu -- bash -lc "just check"`) | exit 0, all tests pass |
| Fast unit subset | `uv run pytest tests/unit/test_tasks_e2e_groups.py tests/unit/test_run_supervisor.py tests/unit/test_log_view.py -q` | all pass |
| Lint | `uv run ruff check tasks.py tools/run_supervisor.py tools/log_view.py` | exit 0 |
| Typecheck | `uv run ty check tasks.py tools/` | exit 0 |

## Scope

**In scope** (the only files you should modify):
- `tasks.py`
- `tools/run_supervisor.py`
- `tools/log_view.py`
- `tests/unit/test_tasks_e2e_groups.py`, `tests/unit/test_run_supervisor.py`,
  `tests/unit/test_log_view.py` (extend as needed)
- `plans/README.md` (status row)

**Out of scope** (do NOT touch, even though they look related):
- `tools/preflight.py`, `tools/log_summary.py`, `tools/sim_cleanup.py`,
  `tools/gcs_heartbeat.py` — restructures already vetted and REJECTED
  (plans/README.md Round 7 rejected list).
- The verdict wording/exit-code contract (`tools/cli_verdict.py`,
  documented in AGENTS.md) — messages must stay recognizably the same.
- `silence_s`/`deadline_s` values — tuned from live measurement (Round 8).

## Git workflow

- Branch: `advisor/084-run-path-dedup`
- Conventional commits (repo style, e.g. `refactor(cli): ...`, `fix(cli): ...`).
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Extract the failure-recording helper in `_run_e2e_sim_group`

Inside `_run_e2e_sim_group`, hoist the config dict once at the top of the
function body:

```python
config = {"vision": vision, "overlay": overlay, "model": model, "world": world}
```

Add a local closure (a nested function is fine — it closes over `registry`,
`failed_claims`, `config`):

```python
def record_failure(s: str, reason: str, *, write_report: bool) -> None:
    if registry is not None and failed_claims is not None:
        failed_claims.add(claim_for_scenario(registry, s) or s)
    if write_report:
        (LOG_DIR / f"scenario_{s}.json").write_text(
            _fallback_scenario_report(s, reason, config), encoding="utf-8"
        )
```

Move `from capabilities import claim_for_scenario` to one import at the top
of the function (it is currently imported inside four separate blocks).
Rewrite the five sites to use it:

- sim-never-ready block (`:1210-1229`): one loop per scenario calling
  `record_failure(s, "sim_never_ready", write_report=True)` then
  `_write_run_record_for(...)` — this also merges the current double loop
  over `scenarios` into one.
- prerequisite-skip block: `record_failure(s, f"prerequisite_failed:{blocker}", write_report=True)`.
- the three verdict arms: derive the reason first, then one shared block:

```python
if stuck is not None:
    reason, msg = f"stuck:{stuck}", f"  [STUCK] {s} killed by supervisor ({stuck}); read the stack log, not the mission events"
elif rc != 0:
    reason, msg = "crashed_before_report", f"  [FAIL] {s} exited {rc} without writing a report; synthesizing crashed_before_report"
elif not fresh:
    reason, msg = "no_report_written", f"  [FAIL] {s} exited 0 but wrote no report; counting as FAIL"
else:
    reason, msg = None, None
if reason is not None:
    fails += 1
    if fresh:  # report exists; keep it, only mark the claim
        record_failure(s, reason, write_report=False)
    else:
        print(msg, file=sys.stderr)
        record_failure(s, reason, write_report=True)
```

Behavior notes to preserve exactly: today the `[STUCK]` message prints even
when `fresh` is True (only the report write is skipped) — keep that: print
`msg` unconditionally for the stuck case if you want byte-identical output,
OR simplify as above only if the tests don't pin it. Check
`tests/unit/test_tasks_e2e_groups.py` first and match whatever it asserts.
The `crashed_before_report` message currently only prints when `not fresh` —
preserve that.

**Verify**: `uv run pytest tests/unit/test_tasks_e2e_groups.py -q` → all pass.

### Step 2: Extract the run-failure hint helper

Add a module-level helper in `tasks.py`:

```python
def _print_run_failure_hint(record_stem: str, t_end: int) -> None:
    print(
        f"next: just log events --run {record_stem} | "
        f'rg -C5 "t={t_end}\\." logs/latest.log'
    )
```

Call it from both sites (`tasks.py:1347-1353` and `tasks.py:1527-1533`),
keeping each site's existing guard condition.

**Verify**: `uv run ruff check tasks.py` → exit 0; grep shows exactly one
occurrence of `rg -C5` in `tasks.py`.

### Step 3: Delete the unbounded `run_cmd` fallback

Replace the `if cfg is None:` arm of `run_cmd` (`tasks.py:1495-1507`) with a
precondition failure:

```python
if cfg is None:
    print(
        f"No declared sim config for '{name}' in tests/capabilities.toml. "
        "Add the claim entry (see `just scenario-new` output) so the run is "
        "bounded and recorded; every shipped scenario declares one.",
        file=sys.stderr,
    )
    raise typer.Exit(int(ExitCode.PRECONDITION))
```

The `else:` arm becomes the unconditional body. Remove the now-false
docstring sentence "Scenarios with no declared config fall back to running
against whatever sim is already up." and keep the "bounded; always leaves a
run record" contract line — it is now true.

**Verify**: `grep -n "running against the existing sim" tasks.py` → no
matches; `uv run pytest tests/unit -q -k "run or e2e"` → all pass.

### Step 4: Delete the dead `--wait` flag on `e2e`

Remove the `wait: bool = typer.Option(...)` parameter (`tasks.py:1401-1406`)
and the comment line referencing "`--wait` is the deprecated no-op alias"
(`tasks.py:1448`).

**Verify**: `grep -n '"--wait"' tasks.py` → no matches; `uv run python
tasks.py e2e --help` → exits 0, no `--wait` in output.

### Step 5: Share the incremental-read primitive between supervisor and log_view

In `tools/log_view.py`, extract the file-level primitive from `read_since`:

```python
def read_new(log_path: Path, offset: int) -> tuple[list[str], int]:
    """Lines appended past *offset*; new offset. Truncation resets to 0."""
    size = log_path.stat().st_size if log_path.exists() else 0
    if size < offset:
        offset = 0
    lines: list[str] = []
    if size > offset:
        with log_path.open("r", encoding="utf-8", errors="replace") as fh:
            fh.seek(offset)
            lines = fh.read().splitlines()
    return lines, size
```

`read_since` keeps its cursor-file handling and calls `read_new`. In
`tools/run_supervisor.py:217-224`, replace the inline stat/seek/read block
with `new, new_offset = log_view.read_new(log_path, offset)`; update
`offset`/`last_growth` only when `new` is non-empty exactly as today
(today: `last_growth` updates when `size > offset`, i.e. when `new` is
non-empty — preserve that equivalence). Add the `import log_view` at the top
of `run_supervisor.py` beside its existing `import reports`.

**Verify**: `uv run pytest tests/unit/test_run_supervisor.py tests/unit/test_log_view.py -q` → all pass.

### Step 6: Full gate

**Verify**: `just check` → exit 0. If a live sim is available, the operator
regression sign-off is `just run 01_arm_takeoff` → PASS verdict and a fresh
record in `logs/runs/`; plus `just run <bogus_name>` → usage error, and a
scenario name that exists but has no registry entry → exit 3 with the new
message (you can test this by pointing `--` at a scratch copy of the
registry only if a test does; otherwise leave to the operator).

## Test plan

- Extend `tests/unit/test_tasks_e2e_groups.py` with: (a) a case asserting a
  STUCK outcome adds the claim to `failed_claims` AND leaves an existing
  fresh report untouched; (b) a case asserting `crashed_before_report` is
  synthesized when rc!=0 and no fresh report exists. Model after the
  existing tests in that file.
- Add one `read_new` unit in `tests/unit/test_log_view.py`: append → returns
  new lines + new offset; truncate → resets and returns full content.
- Add one `run_cmd`-no-config test if the file already has a pattern for
  invoking typer commands (check for `CliRunner` usage); if none exists,
  skip — the grep done-criterion covers the deletion.

## Done criteria

- [ ] `just check` exits 0
- [ ] `python3 -c "import ast,sys; src=open('tasks.py').read(); print(sum(isinstance(n,(ast.If,ast.For,ast.While,ast.Try,ast.Match)) for n in ast.walk(ast.parse(src))))"` prints ≤ 130 (was 139)
- [ ] `grep -c "_fallback_scenario_report" tasks.py` ≤ 3 (definition + ≤2 call sites: the helper and, at most, one other)
- [ ] `grep -n '"--wait"' tasks.py` → no matches
- [ ] `run_cmd` contains no `subprocess.run` without the supervisor (grep `subprocess.run` in the `run_cmd` body → none)
- [ ] No files outside the in-scope list modified (`git status`)
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- The excerpts above don't match the live code (drift).
- `tests/unit/test_tasks_e2e_groups.py` pins output strings that the Step 1
  consolidation cannot reproduce without divergent per-arm code — report
  which string, don't weaken the test.
- You find a caller (test, doc, or script) that genuinely depends on the
  no-config `run` fallback executing a scenario — Step 3 then needs a
  maintainer decision (wrap in supervisor vs delete).
- `just check` fails for a reason unrelated to your diff twice in a row.

## Maintenance notes

- The reviewer should scrutinize Step 1's `fresh`-handling: the consolidated
  block must write a fallback report exactly when the scenario did not write
  a fresh one, never overwriting a fresh FAIL report (it carries real detail).
- If a hardware e2e supervisor ever appears, `record_failure` is the seam to
  lift into `tools/` (the Round 6 rejection of that extraction stands until
  then).
- Deferred: none.
