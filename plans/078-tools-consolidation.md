# Plan 078: tools/ consolidation - reports.py merge, shared probes, log_query fold-in, check_docs cache

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in "STOP conditions" occurs, stop and report - do not
> improvise. When done, update this plan's row in `plans/README.md`.
>
> **Drift check (run first)**: written against tools/ AFTER 068 and 076 (and
> ideally 077) have landed. Confirm `rg "e2e_report|scenario_status_tool|e2e_status_tool" tasks.py`
> shows the 076 import-based call sites. 068 owns `tools/preflight.py`'s port
> checks; this plan does NOT touch preflight. STOP on structural surprises in
> the excerpts below.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: LOW (file moves + mechanical rewires; every moved function keeps
  its signature and is unit-covered)
- **Depends on**: 076 (hard); 068 (ordering, it edits `tools/e2e_status.py`);
  077 recommended first (same tasks.py file)
- **Category**: simplification (complexity-reduction push, Round 7)
- **Planned at**: commit `d769ffe`, 2026-07-17

## Why this matters

tools/ is 22 scripts, 3,067 lines, and carries three kinds of accidental
complexity this plan removes without changing any output:

1. **Three verdict-reader files that are one module.** `e2e_report.py` (58),
   `e2e_status.py` (89), `scenario_status.py` (60) all read
   `logs/scenario_*.json` / `logs/e2e_state.json` and format via
   `cli_verdict`; they even import each other's privates
   (`scenario_status` imports `e2e_report._detail_str`, `e2e_status` imports
   `e2e_report.build_block`). After 076 nothing spawns them as scripts.
2. **Duplicated stack probes.** `status._port_open` == `wait_ready._port_open`
   (and preflight holds the inverse); `status._get_nodes_via_ws` and
   `wait_ready._get_topics_via_ws` are the same rosbridge `/rosapi` call with
   a different service string. Two `pid-alive` implementations exist
   (`tasks._pid_running`, `e2e_status._pid_alive`).
3. **A shim file and an O(tokens x repo) loop.** `log_query.py` (37 lines) is
   a delegation shim for two subcommands; `check_docs.check_token` re-reads
   the whole text corpus and re-parses the justfile for EVERY identifier
   token.

Docs never reference these filenames (verified: no hits in AGENTS/README/docs
outside plans/), so `check_docs` will not fire on the renames.

## Tasks

### Task 1: merge the verdict readers into tools/reports.py

Create `tools/reports.py`:

```python
#!/usr/bin/env python3
"""Verdicts from logs/ artifacts: per-scenario, e2e aggregate, e2e progress.

Merges the former e2e_report.py, e2e_status.py, and scenario_status.py. Reads
logs/scenario_*.json and logs/e2e_state.json; speaks concise English via
cli_verdict. Exit-code contracts unchanged: build_block 0 all-pass / 1;
build_status 0 finished-all-pass, 1 finished-with-failures-or-died, 2 no run,
3 running; format_scenario_status OK/FAIL/USAGE.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from cli_verdict import ExitCode, format_e2e_block, format_scenario

LOG_DIR = Path(__file__).resolve().parents[1] / "logs"


def _detail_str(passed: bool, detail: dict) -> str:
    items = [f"{k}={v}" for k, v in detail.items() if k != "reason"]
    if passed:
        return ", ".join(items) if items else "ok"
    reason = detail.get("reason", "failed")
    return f"{reason}" + (f" ({', '.join(items)})" if items else "")


def build_block(log_dir: Path) -> tuple[str, int]:
    """Return (english_block, exit_code) from scenario_*.json in ``log_dir``."""
    rows: list[tuple[str, bool, str, float]] = []
    for f in sorted(log_dir.glob("scenario_*.json")):
        try:
            s = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        rows.append(
            (
                str(s["scenario"]),
                bool(s["passed"]),
                _detail_str(bool(s["passed"]), s.get("detail", {})),
                float(s.get("elapsed_s", 0.0)),
            )
        )
    if not rows:
        return ("no scenarios ran (expected logs/scenario_*.json)", int(ExitCode.FAIL))
    block = format_e2e_block(rows)
    code = int(ExitCode.OK) if all(p for _, p, _, _ in rows) else int(ExitCode.FAIL)
    return (block, code)


def pid_alive(pidfile: Path) -> bool | None:
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


def build_status(log_dir: Path, worker_alive: bool | None) -> tuple[str, int]:
    """Return (english_text, exit_code) for the most recent e2e run."""
    state_file = log_dir / "e2e_state.json"
    try:
        state = json.loads(state_file.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return ("no e2e run found (expected logs/e2e_state.json)", 2)

    groups = state.get("groups", [])
    done = sum(1 for g in groups if g.get("state") == "done")
    if state.get("status") == "running":
        if worker_alive is False:
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
            lines.append(build_block(log_dir)[0])
        lines.append(f"RUNNING {current_txt}, last activity {age}")
        return ("\n".join(lines), 3)

    if state.get("status") == "aborted":
        return (
            f"e2e ABORTED after group {done}/{len(groups)} (stopped or crashed; see logs/e2e.log)",
            1,
        )

    block, _code = build_block(log_dir)
    code = 0 if state.get("status") == "passed" else 1
    return (block, code)


def format_scenario_status(log_dir: Path, name: str | None) -> tuple[str, int]:
    """Return ``(verdict_line, exit_code)`` for one scenario report.

    If ``name`` is given, read ``scenario_<name>.json``; otherwise pick the most
    recently modified ``scenario_*.json``. Missing/unreadable returns a message
    with ``ExitCode.USAGE``; otherwise ``OK`` if it passed, ``FAIL`` if not.
    """
    if name:
        path = log_dir / f"scenario_{name}.json"
        if not path.is_file():
            return (f"no scenario report found: {path}", int(ExitCode.USAGE))
    else:
        candidates = sorted(log_dir.glob("scenario_*.json"), key=lambda p: p.stat().st_mtime)
        if not candidates:
            return (f"no scenario report found in {log_dir}", int(ExitCode.USAGE))
        path = candidates[-1]
    try:
        s = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        return (f"unreadable scenario report {path}: {type(e).__name__}: {e}", int(ExitCode.USAGE))
    passed = bool(s["passed"])
    line = format_scenario(
        str(s["scenario"]),
        passed,
        _detail_str(passed, s.get("detail", {})),
        float(s.get("elapsed_s", 0.0)),
    )
    return (line, int(ExitCode.OK) if passed else int(ExitCode.FAIL))
```

NOTE: the `speed_txt` lines shown in the pre-068 `build_status` are absent
above because 068 deletes them; if 068's landed version differs, copy ITS
`build_status` body verbatim (only renaming the `pid_alive` parameter to
`worker_alive`).

Then:

- Delete `tools/e2e_report.py`, `tools/e2e_status.py`,
  `tools/scenario_status.py`.
- tasks.py: replace the three imports with `import reports`; call sites become
  `reports.build_block(LOG_DIR)`,
  `reports.build_status(LOG_DIR, reports.pid_alive(LOG_DIR / "e2e.pid"))`,
  `reports.format_scenario_status(LOG_DIR, name or None)`.
- tasks.py: delete `_pid_running` and replace its one use in `test(e2e)` with
  `reports.pid_alive(E2E_PIDFILE) is True` (identical truth table:
  missing/invalid pidfile -> None -> False; dead -> False; alive or
  PermissionError -> True).
- Merge `tests/unit/test_e2e_report.py` + `test_e2e_status.py` +
  `test_scenario_status.py` into `tests/unit/test_reports.py`: concatenate the
  three files, change the imports to
  `from reports import build_block, build_status, format_scenario_status`,
  dedupe the shared header lines. Assertions unchanged.

- [x] Step 1: create reports.py, delete the three files, rewire tasks.py
- [x] Step 2: merge the test files; `uv run pytest tests/unit/ -q` all pass
- [x] Step 3: `just check` (check_docs runs; confirms no doc referenced the
      old filenames)
- [x] Step 4: commit `refactor(tools): merge verdict readers into reports.py`

### Task 2: shared probes for port + rosapi checks

Create `tools/probes.py`:

```python
#!/usr/bin/env python3
"""Shared local-stack probes: TCP port checks and rosbridge /rosapi calls."""

from __future__ import annotations

import json
import socket
import time


def port_open(port: int, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except OSError:
        return False


def rosapi_call(
    service: str, result_key: str, *, port: int = 9090, timeout: float = 1.0, req_id: str = "probe"
) -> list[str] | None:
    """Call a /rosapi service over the rosbridge WebSocket; None on any failure."""
    try:
        import websocket  # type: ignore[import-untyped]

        ws = websocket.create_connection(f"ws://127.0.0.1:{port}", timeout=timeout)
        ws.send(json.dumps({"op": "call_service", "service": service, "id": req_id}))
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            msg = json.loads(ws.recv())
            if msg.get("op") == "service_response" and msg.get("service") == service:
                ws.close()
                return msg.get("values", {}).get(result_key, [])
        ws.close()
    except Exception:
        pass
    return None
```

Rewire, KEEPING the existing private names as one-line delegates so unit-test
`patch("wait_ready._port_open", ...)`-style targets keep working:

`tools/status.py`: delete the `_port_open` and `_get_nodes_via_ws` bodies;
replace with

```python
from probes import port_open as _port_open


def _get_nodes_via_ws(port: int = 9090, timeout: float = 1.0) -> list[str] | None:
    from probes import rosapi_call

    return rosapi_call("/rosapi/nodes", "nodes", port=port, timeout=timeout, req_id="status_nodes")
```

`tools/wait_ready.py`: delete the `_port_open` and `_get_topics_via_ws`
bodies; replace with

```python
from probes import port_open, rosapi_call


def _port_open(port: int) -> bool:
    return port_open(port, timeout=1.0)


def _get_topics_via_ws(port: int = _ROSBRIDGE_PORT, timeout: float = 1.0) -> list[str] | None:
    return rosapi_call(
        "/rosapi/topics", "topics", port=port, timeout=timeout, req_id="wait_ready_topics"
    )
```

(`_rosbridge_ws_ok` keeps its current body; it already calls `_port_open`.)

Do NOT touch `tools/preflight.py` (068 owns its port semantics, and its
`_port_free` for 8888 is UDP-aware after 068).

- [x] Step 1: apply; `uv run pytest tests/unit/ -q` (test_wait_ready and
      test_status patch module-level names, which still exist)
- [x] Step 2: live spot-check: with `just sim` up, `just status` shows
      `stack: UP` with nodes (ws path); `just stop`
- [x] Step 3: commit `refactor(tools): shared probes for port + rosapi checks`

### Task 3: fold log_query.py into tasks.py

In tasks.py: remove `from log_query import app as log_app`; add
`from log_summary import main as log_summary_main` to the tools import block;
define before the `app.add_typer(log_app, ...)` line:

```python
log_app = typer.Typer()


@log_app.command()
def summary(
    log: Path = typer.Option(Path("./logs/latest.log"), "--log"),
    out: Path = typer.Option(Path("./logs/latest_summary.json"), "--out"),
    run_id: str | None = typer.Option(None, "--run-id"),
) -> None:
    """(Re)generate logs/latest_summary.json from logs/latest.log and print it."""
    log_summary_main(log=log, out=out, run_id=run_id)


@log_app.command()
def tail(log: Path = typer.Option(Path("./logs/latest.log"), "--log")) -> None:
    """Follow the live session log (logfmt is already readable)."""
    if not log.exists():
        log.parent.mkdir(parents=True, exist_ok=True)
        log.touch()
    subprocess.run(["tail", "-f", str(log)], check=False)
```

Delete `tools/log_query.py`. Update the `check_docs.py` `_SUBCOMMANDS` comment
(it names `tools/log_query.py` as a source of log subcommands; point it at
`tasks.py` instead).

- [x] Step 1: apply; `just log summary` and `just log tail` behave as before
      (`just log topics` unchanged, it was already defined in tasks.py)
- [x] Step 2: `just check`
- [x] Step 3: commit `refactor(tasks): absorb the two-command log_query shim`

### Task 4: cache check_docs corpus scans

`tools/check_docs.py`: add `from functools import lru_cache` and decorate:

```python
@lru_cache(maxsize=None)
def _recipes(root: Path) -> frozenset[str]:
```

(change its return from `set` to `frozenset(recipes)`), and

```python
@lru_cache(maxsize=None)
def _corpus_text(root: Path) -> str:
```

No call-site changes; `check_token(token, kind, root)` keeps its signature so
all 8 `test_check_docs.py` call sites pass unmodified. Membership is the only
use of `_recipes`' result, so frozenset is drop-in. Each pytest tmp_path is a
distinct cache key, so tests that build different roots are unaffected.

- [x] Step 1: apply; `uv run pytest tests/unit/test_check_docs.py -q` all pass
- [x] Step 2: `time uv run python tools/check_docs.py` - expect a large drop
      (the corpus was re-read per identifier token); record before/after in
      the commit message
- [x] Step 3: commit `perf(check_docs): scan the corpus and justfile once, not per token`

### Task 5: final gate + metrics

- [x] `just check` all pass
- [x] `just test e2e` all 8 PASS (one full live gate for the whole plan)
- [x] Record: `ls tools/*.py | wc -l` (22 -> 19),
      `git ls-files 'tools/*.py' | xargs wc -l | tail -1` (expect roughly
      3,067 -> ~2,800), tests file count (62 -> 60)
- [x] Update `plans/README.md` row

## STOP conditions

- Any test needs an assertion (not import-path) change: STOP and report; the
  merges are supposed to be behavior-identical.
- `just e2e-status` output differs from pre-change for the same state file:
  STOP.

## Explicitly out of scope (investigated, keep as-is)

- `tools/cli_verdict.py`: stays its own module; it is the verdict CONTRACT,
  imported by reports.py and tasks.py, and `tests/scenarios/_common.py`
  mirrors it by design (scenario scripts run without tools/ on the path).
- `tools/preflight.py` restructure: its CC-20 `main` is a sequential
  checklist; table-driving it trades readability for a metric. 068 fixes its
  real defects.
- `tools/log_summary.py:build_run_summary` (CC 22): a single-pass accumulator
  over log records; splitting it moves branches without removing any. The
  logfmt pipeline design was endorsed in Round 4b and stands.
- `tools/sim_cleanup.py`: the kill/never-kill match lists are deliberate,
  documented safety precision. Not duplication.
- `tools/gcs_heartbeat.py`: standalone MAVLink runtime process; its loop
  complexity is protocol-driven, unit-covered (test parity with
  `_start_gz_px4.sh`), and live-verified. Leave.
