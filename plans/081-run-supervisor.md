# Plan 081: run supervisor - bounded scenario execution, heartbeat, run records, STUCK verdict

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in "STOP conditions" occurs, stop and report - do not
> improvise. When done, update this plan's row in `plans/README.md`.
>
> **Drift check (run first)**: written against main `82c21d0`. Confirm:
> - `rg "subprocess.run\(\n?\s*\[\"uv\", \"run\", \"python\", f\"tests/scenarios" tasks.py -U`
>   hits inside `_run_e2e_sim_group` (the call this plan wraps). If the
>   scenario spawn has moved or changed shape: STOP.
> - `ls tools/run_supervisor.py` does not exist yet.
> - `rg "logs/heartbeat|run.pid" tasks.py tools/` returns nothing.
> - Plan 080 need NOT have landed (no shared files), but land 081 before 082.

## Status

- **Priority**: P1
- **Effort**: M/L
- **Risk**: MED (wraps the scenario spawn used by `just scenario` AND e2e;
  behavior pinned by unit tests with fake processes + a full live e2e gate)
- **Depends on**: none hard; before 082 (082 reads this plan's artifacts)
- **Category**: agent-first CLI redesign (spec: `plans/079-agent-first-cli-design.md`)
- **Planned at**: commit `82c21d0`, 2026-07-17

## Why this matters

Layers 2+3 of the spec's termination guarantee. Today
`_run_e2e_sim_group` runs each scenario with a bare
`subprocess.run(["uv", "run", "python", f"tests/scenarios/{s}.py"])`: if the
scenario process wedges (asyncio hang, rclpy spin stall), nothing ends it -
the exact "mission never ends" failure the spec exists to kill. This plan
makes every scenario execution bounded and always leave a terminal artifact:

- `tools/run_supervisor.py`: hard wall-clock deadline + log-silence watchdog
  around the scenario process; rewrites `logs/heartbeat` (one logfmt line)
  every poll; kills on breach.
- Run records at `logs/runs/<name>_<ts>.json`
  (`{verdict, reason, t_start, t_end, last_phase, detail}`), written for
  EVERY outcome. Verdicts: `PASS` / `FAIL` / `STUCK`. (`ABORTED` is
  synthesized by plan 082's `wait` when a supervisor pid died recordless.)
- `STUCK` is a distinct third verdict: FAIL means "flew and missed criteria,
  read the mission events"; STUCK means "the harness or stack wedged, read
  the stack log".

Records are FILES in `logs/runs/`; the bag-recording run DIRS
(`logs/runs/<ts>/` from plans 009-011) coexist - `skein_analyze.resolve_run_dir`
resolves ids to dirs and is unaffected by sibling `.json` files.

## Tasks

### Task 1: heartbeat derivation + run records (pure, TDD)

**Files**: create `tools/run_supervisor.py`;
test `tests/unit/test_run_supervisor.py`.

- [ ] Step 1: failing tests:

```python
from run_supervisor import derive_heartbeat, format_heartbeat, write_run_record, list_run_records

def test_derive_heartbeat_from_log_lines():
    lines = [
        't=10.0 src=mission_manager event=TRANSITION from=takeoff to=follow guard=armed_at_altitude',
        't=12.5 src=px4 text="some chatter"',
        't=14.0 src=offboard_controller event=ARM_COMMAND_SENT',
    ]
    hb = derive_heartbeat(lines, wall_now=100.0, wall_last_event=97.0)
    assert hb["phase"] == "follow"
    assert hb["t"] == 14.0
    assert hb["last_event"] == "ARM_COMMAND_SENT"
    assert hb["last_event_age_s"] == 3.0

def test_derive_heartbeat_empty():
    hb = derive_heartbeat([], wall_now=5.0, wall_last_event=None)
    assert hb["phase"] == "unknown" and hb["last_event"] is None

def test_format_heartbeat_is_one_logfmt_line():
    line = format_heartbeat({"t": 14.0, "phase": "follow", "last_event": "X", "last_event_age_s": 3.0})
    assert "\n" not in line and "phase=follow" in line

def test_run_record_roundtrip_and_prune(tmp_path):
    for i in range(55):
        write_run_record(tmp_path, f"s{i}", "PASS", None, 0.0, 1.0, "done", {}, keep=50)
    recs = list_run_records(tmp_path)
    assert len(recs) == 50
    assert recs[0]["name"] == "s54"  # newest first
    assert recs[0]["verdict"] == "PASS"
```

- [ ] Step 2: `uv run pytest tests/unit/test_run_supervisor.py -q` fails
      (module missing).
- [ ] Step 3: implement. Skeleton (reuse `log_summary.parse_logfmt` for line
      parsing - import it, do not re-implement):

```python
#!/usr/bin/env python3
"""Bounded scenario execution + always-written run records.

The supervisor guarantees the spec invariant "no command may be unbounded":
a scenario process gets a hard wall-clock deadline and a log-silence
watchdog; breach kills it and the outcome is recorded as STUCK. Every run
(PASS/FAIL/STUCK) leaves logs/runs/<name>_<ts>.json; logs/heartbeat is
rewritten each poll so status/wait commands read files, never ROS.
"""
from __future__ import annotations

import json, os, signal, subprocess, time
from pathlib import Path

from log_summary import parse_logfmt

LOG_DIR = Path(__file__).resolve().parents[1] / "logs"
RUNS_DIR = LOG_DIR / "runs"
HEARTBEAT = LOG_DIR / "heartbeat"
RUN_PID = LOG_DIR / "run.pid"

VERDICTS = ("PASS", "FAIL", "STUCK", "ABORTED")

def derive_heartbeat(lines, wall_now, wall_last_event): ...
def format_heartbeat(hb: dict) -> str: ...
def write_run_record(runs_dir, name, verdict, reason, t_start, t_end,
                     last_phase, detail, *, keep=50) -> Path: ...
def list_run_records(runs_dir=RUNS_DIR, limit=50) -> list[dict]: ...
```

`derive_heartbeat` scans lines with `parse_logfmt`: `phase` = `to=` of the
last `event=TRANSITION`, `t` = max `t` seen, `last_event` = last `event=`
value, `last_event_age_s = wall_now - wall_last_event` (None-safe).
`write_run_record` writes `<name>_<YYYYmmdd_HHMMSS>.json` with keys
`{"name", "verdict", "reason", "t_start", "t_end", "last_phase", "detail",
"recorded_at"}`, then prunes oldest-by-mtime beyond `keep`.
`list_run_records` returns newest-first dicts (skip unparseable files).

- [ ] Step 4: tests pass.
- [ ] Step 5: commit `feat(tools): run_supervisor heartbeat derivation + run records`

### Task 2: the supervise loop (fake-process TDD)

**Files**: modify `tools/run_supervisor.py`; test
`tests/unit/test_run_supervisor.py`.

- [ ] Step 1: failing tests (fake child processes, tmp log files - no sim):

```python
def test_supervise_clean_exit(tmp_path):
    log = tmp_path / "latest.log"; log.write_text("")
    rc, stuck = supervise(
        ["python", "-c", "print('ok')"], "s", deadline_s=10, silence_s=10,
        log_path=log, cwd=tmp_path, poll_s=0.05)
    assert rc == 0 and stuck is None

def test_supervise_deadline_kills(tmp_path):
    log = tmp_path / "latest.log"
    # keep the log growing so ONLY the deadline can fire
    child = "import time\nimport pathlib\n" \
            "p=pathlib.Path('latest.log')\n" \
            "[ (p.open('a').write('t=1 src=x chatter\\n'), time.sleep(0.05)) for _ in range(200) ]"
    rc, stuck = supervise(["python", "-c", child], "s", deadline_s=0.5,
                          silence_s=60, log_path=log, cwd=tmp_path, poll_s=0.05)
    assert rc is None and stuck == "deadline_exceeded"

def test_supervise_silence_kills(tmp_path):
    log = tmp_path / "latest.log"; log.write_text("")
    rc, stuck = supervise(["python", "-c", "import time; time.sleep(60)"], "s",
                          deadline_s=60, silence_s=0.3, log_path=log,
                          cwd=tmp_path, poll_s=0.05)
    assert rc is None and stuck == "log_silent"

def test_supervise_writes_heartbeat_and_pid(tmp_path):
    # during a short run, heartbeat file exists and run.pid is cleaned after
    ...
```

- [ ] Step 2: run, confirm FAIL.
- [ ] Step 3: implement:

```python
def supervise(argv, name, *, deadline_s=300.0, silence_s=30.0, log_path,
              cwd, poll_s=1.0, heartbeat_path=None, pid_path=None):
    """Run argv bounded. Returns (returncode, None) on self-exit or
    (None, reason) after killing a wedged child. reason in
    {"deadline_exceeded", "log_silent"}. Always removes pid_path; leaves the
    last heartbeat for post-mortem."""
    heartbeat_path = heartbeat_path or HEARTBEAT
    pid_path = pid_path or RUN_PID
    proc = subprocess.Popen(argv, cwd=str(cwd))
    pid_path.write_text(str(proc.pid))
    start = time.monotonic()
    offset = log_path.stat().st_size if log_path.exists() else 0
    last_growth = time.monotonic()
    tail: list[str] = []
    wall_last_event: float | None = None
    try:
        while True:
            rc = proc.poll()
            size = log_path.stat().st_size if log_path.exists() else 0
            if size < offset:  # log truncated (new boot): restart cursor
                offset = 0
            if size > offset:
                with log_path.open("r", encoding="utf-8", errors="replace") as fh:
                    fh.seek(offset)
                    new = fh.read().splitlines()
                offset = size
                last_growth = time.monotonic()
                if any("event=" in ln for ln in new):
                    wall_last_event = time.time()
                tail = (tail + new)[-400:]
            hb = derive_heartbeat(tail, time.time(), wall_last_event)
            hb["scenario"] = name
            heartbeat_path.write_text(format_heartbeat(hb) + "\n")
            if rc is not None:
                return rc, None
            if time.monotonic() - start > deadline_s:
                _kill(proc); return None, "deadline_exceeded"
            if time.monotonic() - last_growth > silence_s:
                _kill(proc); return None, "log_silent"
            time.sleep(poll_s)
    finally:
        pid_path.unlink(missing_ok=True)

def _kill(proc):
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill(); proc.wait(timeout=5)
```

- [ ] Step 4: tests pass. `ty check tools/run_supervisor.py` clean.
- [ ] Step 5: commit `feat(tools): supervise() - deadline + log-silence bounded child`

### Task 3: wire into `_run_e2e_sim_group` (every scenario run is supervised)

**Files**: modify `tasks.py` (`_run_e2e_sim_group`, imports); test: live gates.

- [ ] Step 1: in `tasks.py` add `import run_supervisor` next to the other
      tools imports. In `_run_e2e_sim_group`, replace

```python
            res_s = subprocess.run(
                ["uv", "run", "python", f"tests/scenarios/{s}.py"], cwd=str(ROOT)
            )
```

with

```python
            rc, stuck = run_supervisor.supervise(
                ["uv", "run", "python", f"tests/scenarios/{s}.py"],
                s,
                deadline_s=300.0,
                silence_s=30.0,
                log_path=LOG_DIR / "latest.log",
                cwd=ROOT,
            )
```

then rework the verdict tail. Preserve EVERY existing branch (fresh-report
check, crashed_before_report, no_report_written, `_auto_record`,
failed_claims bookkeeping) with `rc` in place of `res_s.returncode`, and add
the stuck branch FIRST:

```python
            fresh = report.exists() and report.stat().st_mtime >= started_at
            if stuck is not None:
                fails += 1
                if registry is not None and failed_claims is not None:
                    from capabilities import claim_for_scenario
                    failed_claims.add(claim_for_scenario(registry, s) or s)
                print(f"  [STUCK] {s} killed by supervisor ({stuck}); "
                      "read the stack log, not the mission events", file=sys.stderr)
                if not fresh:
                    report.write_text(
                        _fallback_scenario_report(s, f"stuck:{stuck}",
                            {"vision": vision, "overlay": overlay,
                             "model": model, "world": world}),
                        encoding="utf-8")
            elif rc != 0:
                ... existing failure branches, res_s.returncode -> rc ...
```

- [ ] Step 2: after the verdict branches (all outcomes, including
      `_auto_record`'s), write the run record - one call, deriving fields
      from the scenario report just written/read:

```python
            _write_run_record_for(s, report, stuck)
```

with this helper added near `_fallback_scenario_report`:

```python
def _write_run_record_for(name: str, report: Path, stuck: str | None) -> None:
    """Always-written run record (spec: verdict-file contract). Never raises."""
    try:
        s = json.loads(report.read_text(encoding="utf-8"))
    except Exception:
        s = {"passed": False, "detail": {"reason": "unreadable_report"}}
    hb = {}
    try:
        hb = run_supervisor.parse_heartbeat(run_supervisor.HEARTBEAT.read_text())
    except Exception:
        pass
    verdict = "STUCK" if stuck else ("PASS" if s.get("passed") else "FAIL")
    reason = f"stuck:{stuck}" if stuck else s.get("detail", {}).get("reason")
    run_supervisor.write_run_record(
        run_supervisor.RUNS_DIR, name, verdict, reason,
        t_start=hb.get("t_start", 0.0), t_end=hb.get("t", 0.0),
        last_phase=hb.get("phase", "unknown"), detail=s.get("detail", {}))
```

`parse_heartbeat` (add to run_supervisor with a unit test): inverse of
`format_heartbeat` via `parse_logfmt`. `t_start` is supervise-state, not
derivable from the 400-line tail: `supervise` keeps the FIRST `t` it parses
this supervision in a local and injects `hb["t_start"] = t_first` before
each `format_heartbeat` write (extend the heartbeat tests accordingly).
Also call `_write_run_record_for` in the two pre-flight failure paths
(`sim_never_ready` and prerequisite-skip loops), after each fallback report
write, so those runs are recorded as FAIL too.

Finally, the spec's evidence link: in `_auto_record`'s payload (or the dict
it passes to `cap_evidence`), add `"run_record": <record filename stem>` so
committed evidence names the run record it came from. Thread the stem from
`_write_run_record_for`'s return value (make it return the record `Path`).
Confirm with `rg "run_record" tools/cap_evidence.py tasks.py` after wiring
and one recorded PASS in the live gate.

- [ ] Step 3: teardown hygiene: in `tasks.py` `_teardown()` (or
      `sim_cleanup` if that is where log flags are removed - match the
      existing pattern for `/tmp/gcs_params_flag`), delete `logs/heartbeat`
      and `logs/run.pid` so a stale heartbeat never describes a dead stack.
- [ ] Step 4: `just check` passes.
- [ ] Step 5: commit `feat(tasks): every scenario run supervised; run records always written`

### Task 4: live gate (operator)

- [ ] `just scenario 01_arm_takeoff` PASS; `ls logs/runs/` shows
      `01_arm_takeoff_<ts>.json` with `"verdict": "PASS"`; `cat logs/heartbeat`
      shows the final phase.
- [ ] Forced-STUCK check: `just sim` (disarmed boot, no auto_arm), then run
      a scenario that waits for flight, e.g.
      `uv run tasks.py scenario 03_waypoint` against the wrong sim - EITHER
      the scenario's own timeout FAILs it (fine: record says FAIL) OR, to
      force the supervisor path deterministically, temporarily run with
      `deadline_s=20` (edit, run, revert) and confirm a `"verdict": "STUCK"`
      record + the `[STUCK]` stderr line. Report which path was exercised.
- [ ] `just test e2e` all 8 PASS, exit 0; `ls logs/runs/*.json | wc -l` >= 8.
- [ ] Update `plans/README.md` row.

## STOP conditions

- Any e2e scenario that passed on main now FAILs or STUCKs: the silence/
  deadline defaults are too tight for real runs. Do not just raise them -
  measure (`rg "t=" logs/latest.log | tail`), report, and wait for
  maintainer input.
- `logs/e2e_state.json` keys change: STOP (082's wait and reports.py parse it).
- If `skein_analyze` `latest` resolution breaks with record files present in
  `logs/runs/` (it should not - it resolves dirs): STOP, do not patch skein
  behavior ad hoc.

## Explicitly out of scope

- Per-scenario `deadline_s` in `tests/capabilities.toml` (YAGNI until a
  scenario legitimately needs > 300s; the flag threading lands with the
  regrammar in 083 if ever).
- `wait` / `runs` / `log since` commands (plan 082).
- Renaming any CLI command (plan 083).
