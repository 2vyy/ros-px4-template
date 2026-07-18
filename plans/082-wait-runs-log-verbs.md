# Plan 082: agent read-side - `wait ready|run`, `runs`, `log since|events`, contextual disclosure

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in "STOP conditions" occurs, stop and report - do not
> improvise. When done, update this plan's row in `plans/README.md`.
>
> **Drift check (run first)**: plan 081 MUST have landed. Confirm:
> - `rg "run_supervisor" tasks.py` hits; `ls tools/run_supervisor.py` exists.
> - `rg "write_run_record|list_run_records" tools/run_supervisor.py` hits.
> - `rg "def since|def events" tasks.py tools/` returns nothing yet.
> This plan ADDS commands under the current names (`just wait`, `just runs`,
> `just log since`); plan 083 renames/deletes the old surface afterwards.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: LOW (additive commands over files written by 081; no runtime or
  launch changes; everything pytest-verifiable except one live smoke)
- **Depends on**: 081 (hard)
- **Category**: agent-first CLI redesign (spec: `plans/079-agent-first-cli-design.md`)
- **Planned at**: commit `82c21d0`, 2026-07-17

## Why this matters

The spec's execution contract: an agent starts work detached, then issues
BOUNDED waits; a wait that times out prints a progress snapshot and exits 3 -
a status report, not an error. And the agent-side replacement for `tail -f`:
`log since` returns only what appended since the last call, events-first,
with an aggregate trailer. Both read ONLY files (heartbeat, run records,
e2e_state, latest.log) - no ROS calls, instant, safe to call reflexively.

Exit-code contract (matches the repo's existing 0/1/2/3 and today's
`e2e-status` semantics exactly): `wait run` 0 = terminal PASS, 1 = terminal
FAIL/STUCK/ABORTED, 2 = nothing to wait on, 3 = still running at timeout.

## Tasks

### Task 1: `tools/log_view.py` - cursor reads + events filter (pure, TDD)

**Files**: create `tools/log_view.py`; test `tests/unit/test_log_view.py`.

- [ ] Step 1: failing tests:

```python
from log_view import read_since, filter_events, format_trailer, slice_by_t

def test_read_since_returns_only_new_lines(tmp_path):
    log = tmp_path / "latest.log"; cur = tmp_path / "cursor.json"
    log.write_text("a\nb\n")
    lines, _ = read_since(log, cur)
    assert lines == ["a", "b"]
    log.write_text("a\nb\nc\n")
    lines, _ = read_since(log, cur)
    assert lines == ["c"]

def test_read_since_resets_on_truncation(tmp_path):
    log = tmp_path / "latest.log"; cur = tmp_path / "cursor.json"
    log.write_text("old1\nold2\n"); read_since(log, cur)
    log.write_text("new\n")  # new boot clobbered the log
    lines, _ = read_since(log, cur)
    assert lines == ["new"]

def test_filter_events_keeps_events_and_errors():
    lines = [
        "t=1.0 src=px4 chatter",
        "t=2.0 src=mission_manager event=TRANSITION to=follow",
        "t=3.0 src=position_node level=error msg=bad",
    ]
    kept = filter_events(lines)
    assert len(kept) == 2 and "chatter" not in " ".join(kept)

def test_trailer_counts():
    s = format_trailer(shown=2, raw=3, errors=1)
    assert "2" in s and "3" in s and "--raw" in s

def test_slice_by_t():
    lines = ["t=1.0 a", "t=5.0 b", "t=9.0 c"]
    assert slice_by_t(lines, 4.0, 6.0) == ["t=5.0 b"]

def test_read_since_empty_is_definitive(tmp_path):
    log = tmp_path / "latest.log"; cur = tmp_path / "cursor.json"
    log.write_text("x\n"); read_since(log, cur)
    lines, stats = read_since(log, cur)
    assert lines == [] and stats["raw"] == 0
```

- [ ] Step 2: run, confirm FAIL (module missing).
- [ ] Step 3: implement (reuse `log_summary.parse_logfmt`; cursor file is
      JSON `{"offset": int, "size": int}`; `size < offset` on disk means the
      log was clobbered by a new boot - reset offset to 0):

```python
#!/usr/bin/env python3
"""Cursor-based incremental log reads: 'tail without the -f' for agents."""
def read_since(log_path, cursor_path) -> tuple[list[str], dict]: ...
def filter_events(lines: list[str]) -> list[str]:
    # keep: parsed record has "event" key, or level == "error"
def format_trailer(*, shown: int, raw: int, errors: int) -> str:
    # e.g. "9 events shown (214 raw lines this window, 0 errors); --raw for all"
def slice_by_t(lines: list[str], t0: float, t1: float) -> list[str]: ...
```

- [ ] Step 4: tests pass; `ty check tools/log_view.py` clean.
- [ ] Step 5: commit `feat(tools): log_view - cursor reads, events filter, t-slicing`

### Task 2: `just log since` and `just log events`

**Files**: modify `tasks.py` (log_app); test: CLI smoke below.

- [ ] Step 1: add to `log_app` in tasks.py:

```python
@log_app.command()
def since(raw: bool = typer.Option(False, "--raw", help="All lines, not just events+errors.")) -> None:
    """New log lines since the last `log since` call (events+errors by default)."""
    lines, stats = log_view.read_since(LOG_DIR / "latest.log", LOG_DIR / ".log_cursor.json")
    shown = lines if raw else log_view.filter_events(lines)
    for ln in shown:
        print(ln)
    if not lines:
        print("no new log lines since last call")
        return
    print(log_view.format_trailer(shown=len(shown), raw=stats["raw"], errors=stats["errors"]))

@log_app.command()
def events(run: str = typer.Option("", "--run", help="Run record id (file stem under logs/runs/) to slice to.")) -> None:
    """Events+errors view of the session log, optionally sliced to one run."""
    text = (LOG_DIR / "latest.log").read_text(encoding="utf-8") if (LOG_DIR / "latest.log").exists() else ""
    lines = text.splitlines()
    if run:
        rec_path = run_supervisor.RUNS_DIR / f"{run}.json"
        if not rec_path.is_file():
            print(f"no run record '{run}' (see: just runs)")
            raise typer.Exit(int(ExitCode.USAGE))
        rec = json.loads(rec_path.read_text(encoding="utf-8"))
        lines = log_view.slice_by_t(lines, float(rec["t_start"]), float(rec["t_end"]))
    kept = log_view.filter_events(lines)
    for ln in kept:
        print(ln)
    if not kept:
        print("no events in range" + (f" for run {run}" if run else " (log empty?)"))
```

`import log_view` joins the tools imports. `read_since`'s `stats` dict must
carry `{"raw": n, "errors": n}` (count via `filter` predicate) - align Task 1.

- [ ] Step 2: smoke: `uv run tasks.py log since` twice against a repo with a
      leftover `logs/latest.log` - first call prints events + trailer, second
      prints `no new log lines since last call`. `uv run tasks.py log events
      --run nope` exits 2.
- [ ] Step 3: `just check` passes.
- [ ] Step 4: commit `feat(cli): log since (cursor) + log events (run-sliceable)`

### Task 3: `just runs`

**Files**: modify `tasks.py`; test `tests/unit/test_reports.py` (or a new
`test_runs_cmd.py` if reports tests do not import tasks.py - follow the
existing pattern for testing pure formatters, i.e. put the formatter in
`tools/run_supervisor.py` and test it there).

- [ ] Step 1: failing test for the formatter:

```python
def test_format_runs_table_newest_first_and_empty():
    rows = format_runs([
        {"name": "01_arm_takeoff", "verdict": "PASS", "reason": None, "recorded_at": t0},
        {"name": "02_hover_hold", "verdict": "STUCK", "reason": "stuck:log_silent", "recorded_at": t1},
    ])
    assert "STUCK" in rows and rows.index("02") < rows.index("01") is False  # order preserved as given
    assert format_runs([]) == "no runs recorded (run one with `just scenario <name>`)"
```

- [ ] Step 2: implement `format_runs(records) -> str` in
      `tools/run_supervisor.py` (aligned columns: id stem, verdict, reason
      or "-", age like "3m ago"); test passes.
- [ ] Step 3: add to tasks.py:

```python
@app.command()
def runs() -> None:
    """Recent mission/scenario run records: id, verdict, reason, age."""
    print(run_supervisor.format_runs(run_supervisor.list_run_records()))
```

- [ ] Step 4: `just check`; `uv run tasks.py runs` on a fresh clone prints
      the definitive empty-state line, exit 0.
- [ ] Step 5: commit `feat(cli): just runs - run-record table with definitive empty state`

### Task 4: `just wait ready|run`

**Files**: modify `tasks.py` (new `wait_app`); test: formatter/resolution
logic in `tools/run_supervisor.py` + `tests/unit/test_run_supervisor.py`;
live smoke below.

Resolution order for `wait run` (put it in a pure, tested helper
`resolve_wait_target(log_dir) -> tuple[str, dict]` in run_supervisor,
returning `("e2e", state)` / `("run", {})` / `("record", rec)` / `("none", {})`):

1. e2e cycle active: `logs/e2e_state.json` status == "running" AND
   `reports.pid_alive(logs/e2e.pid)` is True -> wait on the CYCLE (poll
   `reports.build_status`, finish when its exit code != 3).
2. single run active: `logs/run.pid` alive -> poll until a run record newer
   than the wait's start exists (or pid dies; pid dead + no fresh record =
   synthesize and print `ABORTED: supervisor died recordless`, exit 1).
3. neither: newest run record exists -> print `already finished:` + its
   verdict line, exit 0/1 by verdict; no records at all -> print
   `nothing to wait on (no active run, no records)`, exit 2.

- [ ] Step 1: unit tests for `resolve_wait_target` with tmp dirs faking each
      state (state json + pidfiles with `os.getpid()` for alive / 99999999
      for dead). Run: FAIL, then implement, then PASS.
- [ ] Step 2: add to tasks.py:

```python
wait_app = typer.Typer()
app.add_typer(wait_app, name="wait", help="Bounded waits; a timeout is a status report, not an error.")

@wait_app.command()
def ready(timeout: int = typer.Option(120, "--timeout")) -> None:
    """Block until the stack is ready (topics + rosbridge + GCS params)."""
    if wait_ready.wait(timeout):
        raise typer.Exit(int(ExitCode.OK))
    print(f"still not ready after {timeout}s; next: just log since | just stop")
    raise typer.Exit(int(ExitCode.PRECONDITION))

@wait_app.command("run")
def wait_run(timeout: int = typer.Option(120, "--timeout")) -> None:
    """Block until the active run/e2e cycle reaches a terminal verdict.

    Exit: 0 PASS, 1 FAIL/STUCK/ABORTED, 2 nothing to wait on, 3 timeout
    (prints the heartbeat snapshot - progress, not an error)."""
    deadline = time.monotonic() + timeout
    started = time.time()
    while True:
        kind, payload = run_supervisor.resolve_wait_target(LOG_DIR)
        if kind == "e2e":
            text, code = reports.build_status(LOG_DIR, reports.pid_alive(LOG_DIR / "e2e.pid"))
            if code != 3:
                print(text)
                raise typer.Exit(code)
        elif kind == "run":
            recs = run_supervisor.list_run_records(limit=1)
            if recs and recs[0].get("recorded_at", 0.0) >= started:
                rec = recs[0]
                print(f"{rec['verdict']} {rec['name']}: {rec.get('reason') or 'ok'}")
                raise typer.Exit(0 if rec["verdict"] == "PASS" else 1)
            if not reports.pid_alive(LOG_DIR / "run.pid"):
                print("ABORTED: supervisor died recordless (see logs/latest.log)")
                raise typer.Exit(1)
        elif kind == "record":
            print(f"already finished: {payload['verdict']} {payload['name']}: "
                  f"{payload.get('reason') or 'ok'}")
            raise typer.Exit(0 if payload["verdict"] == "PASS" else 1)
        else:
            print("nothing to wait on (no active run, no records)")
            raise typer.Exit(2)
        if time.monotonic() >= deadline:
            break
        time.sleep(1.0)
```

(`resolve_wait_target` returns `("run", {})` while `run.pid` is alive OR was
alive at wait start - reconcile the exact liveness handling with the unit
tests from Step 1; the pid-dead-recordless branch above is the ABORTED
synthesis the spec requires.)

On the timeout path print the current heartbeat + progress, then the
disclosure line, then exit 3:

```python
    hb = (LOG_DIR / "heartbeat").read_text().strip() if (LOG_DIR / "heartbeat").exists() else "no heartbeat"
    print(f"RUNNING after {timeout}s: {hb}")
    print("next: just wait run --timeout 120 | just log since")
    raise typer.Exit(3)
```

For the e2e-cycle branch print `reports.build_status` text on finish and map
its code through unchanged.

- [ ] Step 3: `just check` passes.
- [ ] Step 4: commit `feat(cli): just wait ready|run - bounded waits with progress-on-timeout`

### Task 5: contextual disclosure on verdicts

**Files**: modify `tasks.py` (`_run_e2e_sim_group` STUCK/FAIL prints,
`scenario()` failure tail); test: none beyond existing (print-only).

- [ ] Step 1: after a FAIL/STUCK run record is written, print one line
      (`_write_run_record_for` returns the record `Path` since 081; read the
      record back for its `t_end` rather than reaching for supervisor
      internals):

```python
                rec = json.loads(record_path.read_text(encoding="utf-8"))
                print(f"next: just log events --run {record_path.stem} | "
                      f"rg -C5 \"t={int(rec.get('t_end') or 0)}\\.\" logs/latest.log")
```

Add the same one-liner to the `scenario()` failure tail after
`_print_failure_digest()` (there, take the newest record from
`run_supervisor.list_run_records(limit=1)`).

- [ ] Step 2: `just check`; commit `feat(cli): verdicts suggest the next command`

### Task 6: live smoke (operator)

- [ ] `just test e2e --detach`, then immediately `uv run tasks.py wait run
      --timeout 30`: prints RUNNING + heartbeat, exit 3. Then
      `uv run tasks.py wait run --timeout 600`: blocks to the aggregate
      block, exit 0.
- [ ] During the same cycle: `uv run tasks.py log since` twice ~20s apart -
      second call shows only the delta with a trailer.
- [ ] After: `uv run tasks.py runs` lists 8 records, all PASS;
      `uv run tasks.py log events --run <one id>` prints only that run's events.
- [ ] Update `plans/README.md` row.

## STOP conditions

- `wait run` exit codes deviating from 0/1/2/3 as specified: STOP (the codes
  are the spec's contract, matched to today's e2e-status).
- Any new command needing ROS/rosbridge access: STOP - the spec requires
  file-only reads for wait/runs/status.
- If `logs/e2e_state.json` shape differs from what `reports.build_status`
  parses (drift from 081): reconcile with reports.py as the source of truth.

## Explicitly out of scope

- `log why` and `wait --until event=<pattern>` (spec: deferred backlog).
- Deleting/renaming old commands, `_SUBCOMMANDS`, AGENTS.md/README rewrites
  (plan 083 - keep this plan additive so 083's diff is pure regrammar).
- Multi-agent cursor files (single-agent assumption is stated in the spec).
