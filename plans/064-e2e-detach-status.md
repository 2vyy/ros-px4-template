# Plan 064: `just test e2e` detaches; `just e2e-status` gives agents cheap progress

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving on. On
> any STOP condition, stop and report. When done, update `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 4f56ebc..HEAD -- tasks.py justfile tools/e2e_report.py tools/cli_verdict.py tests/unit/test_e2e_report.py`
> On any mismatch with the excerpts below, STOP.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: LOW (new surface; the blocking path is preserved behind `--wait`)
- **Depends on**: none (pairs with plan 065; execute 064 first)
- **Category**: dx
- **Planned at**: commit `4f56ebc`, 2026-07-11
- **Spec**: `docs/superpowers/specs/2026-07-11-e2e-detach-and-speed-design.md` (untracked; docs/superpowers is gitignored)

## Why this matters

`just test e2e` holds the terminal for the whole run (profiled 2026-07-11:
~8 min wall for 7 scenarios). Agent harnesses cap long commands; on the
profiled run an agent's wrapper hit a 10-minute cap, lost the exit code, and
re-ran the entire cycle: an 8-minute gate became ~20 minutes. Every other
launch in this repo already detaches (`just sim`, `just hw`); e2e is the one
long runner that does not. The fix is the same contract: kick off, return,
poll. Per-scenario results are already written incrementally
(`logs/scenario_*.json`, gap-free since plan 053); what is missing is a
supervisor that survives the caller and a status command that reads progress
and can tell "slow" from "wedged".

## Current state

- `tasks.py:898-901` — `test` command signature:

  ```python
  def test(
      type: str = typer.Argument("unit", help="Test type: unit, scenario, e2e"),
      arg: str = typer.Option("", "--arg", help="Scenario name (required for scenario test)"),
  ):
  ```

- The e2e branch of `test` (`tasks.py:~930-1010`): smart-build, preflight
  (exit 3 on fail), roster check (exit 3 when empty, from plan 053), then an
  inline loop `for ... in _e2e_sim_groups(configs): fails += _run_e2e_sim_group(...)`,
  then `_summarize_logs_silent()`, `tools/e2e_report.py`, exit 0/1. An
  `atexit` teardown hook is registered inside the command.
- `tasks.py:245-260` — `_spawn_stack` is the detached-launch pattern:
  `subprocess.Popen(..., preexec_fn=os.setsid, stdout=<log fh>, stderr=STDOUT)`.
  It hardcodes `logs/latest.log`; the e2e supervisor needs its own log, so it
  gets a sibling helper, not a reuse.
- `tasks.py:229-242` — `_teardown()` is called by `stop`, by failed launches,
  and at every e2e group boundary. NOTE: the e2e worker itself calls
  `_teardown()` between groups, so the worker process must NOT be killable by
  `sim_cleanup` patterns (suicide). The supervisor is killed only by the
  `stop` command via `logs/e2e.pid`.
- `tools/cli_verdict.py` — `ExitCode` (OK=0, FAIL=1, USAGE=2, PRECONDITION=3),
  `format_e2e_block(rows)`, `format_scenario(...)`.
- `tools/e2e_report.py:27-47` — `build_block(log_dir)` reads
  `scenario_*.json`, returns `(block, code)`. `e2e_status` reuses its row
  logic via import, not copy.
- `justfile` recipes delegate: `test *args:` -> `@just _run test "$@"`;
  `scenario-status *args:` shows the one-command pattern to copy.
- `tests/scenarios/_common.py:write_report` JSON shape:
  `{"scenario", "passed", "elapsed_s", "detail": {...}}`.

## Commands you will need

| Purpose | Command | Expected |
|---------|---------|----------|
| Quality gate | `just check` | exit 0 |
| Targeted tests | `uv run pytest tests/unit/test_e2e_status.py -q` | all pass |
| Live detached run (operator) | `just test e2e` then poll `just e2e-status` | STARTED line, then RUNNING (exit 3), then 7/7 PASS (exit 0) |
| Mid-run abort (operator) | `just stop` during a run, then `just e2e-status` | status aborted, exit 1 |

## Scope

**In scope**:
- `tasks.py` (split `test e2e` into launcher + hidden `e2e-worker`; `--wait`;
  `e2e-status` command; `stop` kills the supervisor; state-file writer)
- `tools/e2e_status.py` (new; pure status builder)
- `tests/unit/test_e2e_status.py` (new)
- `justfile` (`e2e-status` recipe)
- `AGENTS.md`, `README.md` (contract rows)

**Out of scope**:
- `tools/sim_cleanup.py` — do NOT add an e2e-worker kill pattern (worker
  calls `_teardown()` itself; a pattern match would self-kill mid-run)
- Speed factor (plan 065)
- `tools/e2e_report.py` semantics (final report unchanged)

## Git workflow

- Branch: `advisor/064-e2e-detach-status`
- Commit style: `feat(e2e): detach-always test e2e with e2e-status polling`
- Commit after each green step; never commit `logs/`.

## Design contract (implement exactly)

- `just test e2e` = launcher: smart-build + preflight + roster check run
  synchronously (existing exit-3 semantics preserved verbatim), then spawn
  `uv run python tasks.py e2e-worker [--speed <f>]` detached (setsid, stdout
  to `logs/e2e.log`), write `logs/e2e.pid`, print STARTED verdict, exit 0.
- Refuse to start when a live supervisor exists: `logs/e2e.pid` present AND
  pid alive -> print refusal, exit 3.
- `just test e2e --wait` = old blocking behavior: run the worker function
  inline in-process (same exit codes as today).
- Worker maintains `logs/e2e_state.json` via atomic tmp+`os.replace`:

  ```json
  {
    "status": "running|passed|failed|aborted",
    "started_at": 1783760000.0,
    "finished_at": null,
    "speed": 1.0,
    "groups": [
      {"vision": "none", "overlay": "hover", "scenarios": ["01_arm_takeoff"],
       "state": "pending|running|done", "fails": 0}
    ]
  }
  ```

  Updated: once at worker start (all pending), before each group (running),
  after each group (done + fails), at exit (final status + finished_at). A
  `finally` guard writes `aborted` if the worker dies with status still
  `running`.
- `e2e-status` exit codes: 0 finished all-pass; 1 finished-with-failures OR
  supervisor dead while state says running (report as aborted); 2 no state
  file; 3 still running. RUNNING output includes group progress and
  `last activity Ns ago` = age of `logs/latest.log` mtime (the wedge
  detector).
- `stop`: if `logs/e2e.pid` exists, SIGTERM the supervisor's process group
  first, mark state `aborted` if it was `running`, remove the pidfile, then
  the existing `_teardown()`.

## Steps

### Step 1: Extract the worker and add the state writer (no behavior change yet)

In `tasks.py`, add near `_run_e2e_sim_group`:

```python
E2E_STATE = LOG_DIR / "e2e_state.json"
E2E_PIDFILE = LOG_DIR / "e2e.pid"


def _e2e_write_state(state: dict) -> None:
    """Atomically persist e2e progress for `e2e-status` polling."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    tmp = E2E_STATE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, E2E_STATE)
```

Move the body of the e2e branch of `test` (from the
`configs = scenario_sim_configs("sim")` roster check result onward: atexit
registration, group loop, summarize, report, verdict/exit) into a new
function `_e2e_run(configs: list[dict], speed: float = 1.0) -> None` that
raises `typer.Exit` exactly as today, extended with state writes:

```python
def _e2e_run(configs: list[dict], speed: float = 1.0) -> None:
    import atexit

    def cleanup():
        print("Cleaning up E2E simulation...")
        _teardown()

    atexit.register(cleanup)
    gz_resource = f"{ROOT}/sim/worlds:{ROOT}/sim/models"
    group_items = _e2e_sim_groups(configs)
    state = {
        "status": "running",
        "started_at": time.time(),
        "finished_at": None,
        "speed": speed,
        "groups": [
            {"vision": v, "overlay": o, "scenarios": s, "state": "pending", "fails": 0}
            for v, o, s in group_items
        ],
    }
    _e2e_write_state(state)
    try:
        fails = 0
        (LOG_DIR / "latest.log").write_text("", encoding="utf-8")
        for idx, (vision, overlay, scenarios) in enumerate(group_items):
            state["groups"][idx]["state"] = "running"
            _e2e_write_state(state)
            group_fails = _run_e2e_sim_group(
                vision,
                overlay,
                scenarios,
                gz_resource=gz_resource,
                audit_topics=idx == len(group_items) - 1,
            )
            fails += group_fails
            state["groups"][idx]["state"] = "done"
            state["groups"][idx]["fails"] = group_fails
            _e2e_write_state(state)
        ...  # summarize + report + verdict, exactly as the current body
    finally:
        if state["status"] == "running":
            state["status"] = "passed" if fails == 0 else "failed"  # see note
        state["finished_at"] = time.time()
        _e2e_write_state(state)
```

Note on the `finally`: the current body exits via `raise typer.Exit(...)` on
failure; structure the extraction so the final status is computed from
`fails`/report result before the exit is raised (set `state["status"]`
explicitly on each exit path; the `finally` only stamps `finished_at` and
handles the unexpected-exception path by writing `aborted`). `import time`
is already available as `_time` in some scopes; use a module-level
`import time` consistent with the file (check the imports at `tasks.py:16-27`
and reuse what exists; add `import time` at module level if absent).

The e2e branch of `test` now reads (temporarily, until Step 3):

```python
    elif type == "e2e":
        ...  # existing prints, _smart_build(True), preflight, roster check
        _e2e_run(configs)
```

**Verify**: `just check` -> exit 0 (pure refactor; 065's live run re-proves
e2e later, and Step 6 here runs it live anyway).

### Step 2: `tools/e2e_status.py` + unit tests (TDD: tests first)

Create `tests/unit/test_e2e_status.py`:

```python
"""Unit tests for the e2e progress/status builder."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

from e2e_status import build_status


def _write_state(d: Path, **overrides) -> None:
    state = {
        "status": "running",
        "started_at": time.time() - 120,
        "finished_at": None,
        "speed": 1.0,
        "groups": [
            {"vision": "none", "overlay": "hover", "scenarios": ["01_arm_takeoff"],
             "state": "done", "fails": 0},
            {"vision": "aruco", "overlay": "marker_hover", "scenarios": ["05_aruco_hover"],
             "state": "running", "fails": 0},
            {"vision": "none", "overlay": "yaw_demo", "scenarios": ["07_yaw_control"],
             "state": "pending", "fails": 0},
        ],
    }
    state.update(overrides)
    (d / "e2e_state.json").write_text(json.dumps(state), encoding="utf-8")


def _write_scenario(d: Path, name: str, passed: bool) -> None:
    (d / f"scenario_{name}.json").write_text(
        json.dumps(
            {"scenario": name, "passed": passed, "elapsed_s": 5.0,
             "detail": {} if passed else {"reason": "timeout"}}
        ),
        encoding="utf-8",
    )


def test_no_state_file_exits_2(tmp_path: Path) -> None:
    text, code = build_status(tmp_path, pid_alive=None)
    assert code == 2
    assert "no e2e run found" in text.lower()


def test_running_exits_3_and_shows_progress(tmp_path: Path) -> None:
    _write_state(tmp_path)
    _write_scenario(tmp_path, "01_arm_takeoff", True)
    (tmp_path / "latest.log").write_text("x", encoding="utf-8")
    text, code = build_status(tmp_path, pid_alive=True)
    assert code == 3
    assert "RUNNING" in text
    assert "group 2/3" in text
    assert "05_aruco_hover" in text
    assert "PASS 01_arm_takeoff" in text
    assert "last activity" in text


def test_finished_all_pass_exits_0(tmp_path: Path) -> None:
    _write_state(tmp_path, status="passed", finished_at=time.time())
    _write_scenario(tmp_path, "01_arm_takeoff", True)
    text, code = build_status(tmp_path, pid_alive=False)
    assert code == 0
    assert "PASS" in text


def test_finished_with_failures_exits_1(tmp_path: Path) -> None:
    _write_state(tmp_path, status="failed", finished_at=time.time())
    _write_scenario(tmp_path, "01_arm_takeoff", False)
    text, code = build_status(tmp_path, pid_alive=False)
    assert code == 1
    assert "FAIL" in text


def test_dead_supervisor_while_running_is_aborted_exit_1(tmp_path: Path) -> None:
    _write_state(tmp_path)
    text, code = build_status(tmp_path, pid_alive=False)
    assert code == 1
    assert "aborted" in text.lower()
```

Run: `uv run pytest tests/unit/test_e2e_status.py -q` -> FAIL
(`ModuleNotFoundError: e2e_status`). Then create `tools/e2e_status.py`:

```python
#!/usr/bin/env python3
"""Progress/status for a detached e2e run. Speaks concise English.

Reads logs/e2e_state.json (written by the e2e worker) plus the incremental
logs/scenario_*.json reports. Exit codes: 0 finished all-pass, 1 finished
with failures or supervisor died mid-run, 2 no run found, 3 still running.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

from e2e_report import build_block

LOG_DIR = Path(__file__).resolve().parents[1] / "logs"


def _pid_alive(pidfile: Path) -> bool | None:
    """None when no pidfile; else whether the recorded pid is alive."""
    try:
        pid = int(pidfile.read_text().strip())
    except (FileNotFoundError, ValueError):
        return None
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _rows_so_far(log_dir: Path) -> str:
    block, _code = build_block(log_dir)
    return block


def build_status(log_dir: Path, pid_alive: bool | None) -> tuple[str, int]:
    """Return (english_text, exit_code) for the most recent e2e run."""
    state_file = log_dir / "e2e_state.json"
    try:
        state = json.loads(state_file.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return ("no e2e run found (expected logs/e2e_state.json)", 2)

    groups = state.get("groups", [])
    done = sum(1 for g in groups if g.get("state") == "done")
    if state.get("status") == "running":
        if pid_alive is False:
            return (
                "e2e ABORTED: supervisor died mid-run "
                f"(after group {done}/{len(groups)}; see logs/e2e.log)",
                1,
            )
        current = next((g for g in groups if g.get("state") == "running"), None)
        current_txt = (
            f"group {done + 1}/{len(groups)} ({', '.join(current['scenarios'])})"
            if current
            else f"between groups ({done}/{len(groups)} done)"
        )
        latest = log_dir / "latest.log"
        age = f"{time.time() - latest.stat().st_mtime:.0f}s ago" if latest.exists() else "n/a"
        lines = []
        if any(log_dir.glob("scenario_*.json")):
            lines.append(_rows_so_far(log_dir))
        lines.append(f"RUNNING {current_txt}, last activity {age}")
        return ("\n".join(lines), 3)

    block = _rows_so_far(log_dir)
    code = 0 if state.get("status") == "passed" else 1
    return (block, code)


def main() -> None:
    text, code = build_status(LOG_DIR, _pid_alive(LOG_DIR / "e2e.pid"))
    print(text)
    sys.exit(code)


if __name__ == "__main__":
    main()
```

CAVEAT the tests will catch: `build_block` on a dir with scenario files from
a PREVIOUS run would show stale rows. The worker already truncates
`latest.log` at start; extend Step 3's launcher to also delete stale
`logs/scenario_*.json` before spawning the worker (one `for f in
LOG_DIR.glob("scenario_*.json"): f.unlink()` after the roster check). Check
whether `_e2e_run`/existing e2e already does this (`rg -n "scenario_"
tasks.py`); if it does, keep the single existing location.

Run: `uv run pytest tests/unit/test_e2e_status.py -q` -> 5 passed. Commit.

### Step 3: Launcher/worker split + `e2e-status` + `stop` integration

In `tasks.py`:

1. New hidden worker command (hidden so `just --list`/help stay clean):

```python
@app.command("e2e-worker", hidden=True)
def e2e_worker(
    speed: float = typer.Option(1.0, "--speed", help="Physics speed factor."),
) -> None:
    """Internal: the detached e2e supervisor. Launched by `just test e2e`."""
    configs = scenario_sim_configs("sim")
    _e2e_run(configs, speed=speed)
```

2. The e2e branch of `test` becomes the launcher. Signature change:

```python
def test(
    type: str = typer.Argument("unit", help="Test type: unit, scenario, e2e"),
    arg: str = typer.Option("", "--arg", help="Scenario name (required for scenario test)"),
    wait: bool = typer.Option(False, "--wait", help="e2e only: block until the run finishes."),
):
```

e2e branch after the existing smart-build + preflight + roster check
(all unchanged, still synchronous):

```python
        if wait:
            _e2e_run(configs)
            return
        if E2E_PIDFILE.exists() and _pid_running(E2E_PIDFILE):
            print(
                "An e2e run is already in progress (logs/e2e.pid). "
                "Watch: just e2e-status. Stop: just stop.",
                file=sys.stderr,
            )
            raise typer.Exit(int(ExitCode.PRECONDITION))
        for f in LOG_DIR.glob("scenario_*.json"):
            f.unlink()
        out_fh = (LOG_DIR / "e2e.log").open("w", encoding="utf-8")
        proc = subprocess.Popen(
            ["uv", "run", "python", "tasks.py", "e2e-worker"],
            stdout=out_fh,
            stderr=subprocess.STDOUT,
            preexec_fn=os.setsid,
            cwd=str(ROOT),
        )
        E2E_PIDFILE.write_text(str(proc.pid))
        n = len(_e2e_sim_groups(configs))
        print(
            f"E2E STARTED: {len(configs)} scenario(s) in {n} group(s), "
            f"est ~{max(1, round(n * 65 / 60))} min. "
            "Watch: just e2e-status | just log tail. Stop: just stop."
        )
```

with the small helper (place next to `_e2e_write_state`):

```python
def _pid_running(pidfile: Path) -> bool:
    try:
        os.kill(int(pidfile.read_text().strip()), 0)
        return True
    except (ValueError, ProcessLookupError, FileNotFoundError):
        return False
    except PermissionError:
        return True
```

3. New status command + justfile recipe:

```python
@app.command("e2e-status")
def e2e_status_cmd() -> None:
    """Print progress/verdict of the current or last e2e run (poll while detached)."""
    res = subprocess.run(["uv", "run", "python", "tools/e2e_status.py"], cwd=str(ROOT))
    raise typer.Exit(res.returncode)
```

justfile (after the `scenario-status` recipe):

```make
# Print progress/verdict of the current or last detached e2e run
e2e-status:
    @just _run e2e-status
```

4. `stop` command: before its `_teardown()` call, add:

```python
    if E2E_PIDFILE.exists():
        try:
            pid = int(E2E_PIDFILE.read_text().strip())
            os.killpg(pid, signal.SIGTERM)
            print(f"Stopped e2e supervisor (pid {pid}).")
        except (ValueError, ProcessLookupError, PermissionError):
            pass
        E2E_PIDFILE.unlink(missing_ok=True)
        if E2E_STATE.exists():
            try:
                state = json.loads(E2E_STATE.read_text(encoding="utf-8"))
                if state.get("status") == "running":
                    state["status"] = "aborted"
                    state["finished_at"] = time.time()
                    _e2e_write_state(state)
            except json.JSONDecodeError:
                pass
```

(`import signal` at module level if not present; `os.killpg` works because
the worker was spawned with `preexec_fn=os.setsid`.)

**Verify**: `just check` -> exit 0. `uv run tasks.py e2e-status` with no
state -> "no e2e run found", exit 2 (`echo $status` in fish / `echo $?` in
bash).

### Step 4: Docs

- `AGENTS.md` Tooling table, Verification suite row: append "e2e detaches;
  poll with `just e2e-status`". Add to the Common workflows table:
  `| Poll a detached e2e run | just e2e-status |`. In "Command verdicts and
  exit codes", add one sentence: `just test e2e` returns after E2E STARTED;
  `just e2e-status` exits 0 pass / 1 fail-or-aborted / 2 no run / 3 running.
- `README.md` everyday commands: mirror the one-line addition.

**Verify**: `just check` -> exit 0 (docs identifier check covers AGENTS.md).

### Step 5: Kill-tests (fast, no full run)

With no sim running:

1. `uv run tasks.py e2e-status` -> exit 2.
2. Fake a dead supervisor: write `logs/e2e.pid` with pid `99999999` and a
   `logs/e2e_state.json` with `"status": "running"`; `uv run tasks.py
   e2e-status` -> "ABORTED", exit 1. Delete both files afterwards.

### Step 6: Live verification (operator/distrobox)

1. `just test e2e` -> prints `E2E STARTED: ...`, returns in seconds
   (after smart-build+preflight), exit 0.
2. Immediately `just test e2e` again -> refusal, exit 3.
3. Poll `just e2e-status` -> exit 3 with RUNNING + rows accumulating; the
   `last activity` age stays small while healthy.
4. On completion `just e2e-status` -> full 7-row block, 7 PASS, exit 0.
5. `just stop` -> `STOPPED: 0 processes killed` (worker cleaned up after
   itself) and pidfile gone.
6. Start another run; mid-run `just stop`; `just e2e-status` -> aborted,
   exit 1. `just stop` again to be sure nothing survived.
7. `just test e2e --wait` -> old blocking behavior, exits 0 with the final
   block (this re-verifies the inline path end to end).

## Done criteria

- [ ] `just test e2e` returns immediately after STARTED; run completes detached; `just e2e-status` transitions 3 -> 0 across a passing run
- [ ] Double-start refused (exit 3); `--wait` blocks like today (exit 0/1)
- [ ] Mid-run `just stop` yields aborted status (exit 1) and no survivors
- [ ] `uv run pytest tests/unit/test_e2e_status.py -q` all pass; `just check` exit 0
- [ ] AGENTS.md + README rows updated
- [ ] `plans/README.md` row updated

## STOP conditions

- `sim_cleanup.teardown()` kills the worker during group teardown (check
  `logs/e2e.log` for the worker dying at a group boundary): the pattern
  set changed since `4f56ebc` — report, do not widen `_NEVER_BASENAMES`.
- The e2e branch of `test` no longer matches the Step 1 excerpt (plan 065 or
  other work landed first) — reconcile, do not overwrite.

## Maintenance notes

- Plan 065 threads `--speed` through `test e2e` -> `e2e-worker` -> `_e2e_run`;
  the `speed` field in `e2e_state.json` and the worker option exist from this
  plan so 065 only adds plumbing and validation.
- Agent loop after this plan: `just test e2e`, then poll `just e2e-status`
  (~30 s cadence); act on exit != 3. Large `last activity` age with exit 3 =
  wedged stack: `just stop`, inspect `logs/e2e.log` + `logs/latest.log`.
