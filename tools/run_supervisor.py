#!/usr/bin/env python3
"""Bounded scenario execution + always-written run records.

The supervisor guarantees the spec invariant "no command may be unbounded":
a scenario process gets a hard wall-clock deadline and a log-silence
watchdog; breach kills it and the outcome is recorded as STUCK. Every run
(PASS/FAIL/STUCK) leaves logs/runs/<name>_<ts>.json; logs/heartbeat is
rewritten each poll so status/wait commands read files, never ROS.
"""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

import reports
from log_summary import parse_logfmt

LOG_DIR = Path(__file__).resolve().parents[1] / "logs"
RUNS_DIR = LOG_DIR / "runs"
HEARTBEAT = LOG_DIR / "heartbeat"
RUN_PID = LOG_DIR / "run.pid"

VERDICTS = ("PASS", "FAIL", "STUCK", "ABORTED")

_NUMERIC_HB_KEYS = ("t", "t_start", "last_event_age_s")


def derive_heartbeat(lines: list[str], wall_now: float, wall_last_event: float | None) -> dict:
    """Reduce recent log lines to one status dict.

    ``phase`` = ``to=`` of the last TRANSITION, ``t`` = max mission time seen,
    ``last_event`` = last ``event=`` value, ``last_event_age_s`` = wall-clock
    seconds since an event line was last observed (None until the first one).
    """
    phase = "unknown"
    t = 0.0
    last_event: str | None = None
    for line in lines:
        rec = parse_logfmt(line)
        if isinstance(rec.get("t"), float):
            t = max(t, rec["t"])
        event = rec.get("event")
        if event:
            last_event = str(event)
            if event == "TRANSITION" and rec.get("to"):
                phase = str(rec["to"])
    age = None if wall_last_event is None else wall_now - wall_last_event
    return {"t": t, "phase": phase, "last_event": last_event, "last_event_age_s": age}


def format_heartbeat(hb: dict) -> str:
    """One logfmt line; None values are omitted."""
    return " ".join(f"{key}={value}" for key, value in hb.items() if value is not None)


def parse_heartbeat(text: str) -> dict:
    """Inverse of format_heartbeat (numeric fields coerced back to float)."""
    rec = parse_logfmt(text.strip())
    for key in _NUMERIC_HB_KEYS:
        if key in rec:
            try:
                rec[key] = float(rec[key])
            except (TypeError, ValueError):
                pass
    return rec


def _record_files(runs_dir: Path) -> list[Path]:
    """Record FILES newest-first; the bag-recording run DIRS coexist untouched."""
    files = [p for p in runs_dir.glob("*.json") if p.is_file()]
    return sorted(files, key=lambda p: (p.stat().st_mtime_ns, p.name), reverse=True)


def write_run_record(
    runs_dir: Path,
    name: str,
    verdict: str,
    reason: str | None,
    t_start: float,
    t_end: float,
    last_phase: str,
    detail: dict,
    *,
    keep: int = 50,
) -> Path:
    """Write logs/runs/<name>_<ts>.json and prune the oldest beyond ``keep``."""
    runs_dir = Path(runs_dir)
    runs_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    path = runs_dir / f"{name}_{stamp}.json"
    n = 1
    while path.exists():
        path = runs_dir / f"{name}_{stamp}_{n}.json"
        n += 1
    payload = {
        "name": name,
        "verdict": verdict,
        "reason": reason,
        "t_start": t_start,
        "t_end": t_end,
        "last_phase": last_phase,
        "detail": detail,
        "recorded_at": time.time(),
        "record": path.stem,
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    for stale in _record_files(runs_dir)[keep:]:
        stale.unlink(missing_ok=True)
    return path


def list_run_records(runs_dir: Path = RUNS_DIR, limit: int = 50) -> list[dict]:
    """Newest-first record dicts; unparseable files are skipped, dirs ignored."""
    records: list[dict] = []
    for path in _record_files(Path(runs_dir))[:limit]:
        try:
            records.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    return records


def _age(recorded_at: float, now: float | None = None) -> str:
    delta = max(0.0, (time.time() if now is None else now) - recorded_at)
    if delta < 60:
        return f"{delta:.0f}s ago"
    if delta < 3600:
        return f"{delta / 60:.0f}m ago"
    if delta < 86400:
        return f"{delta / 3600:.1f}h ago"
    return f"{delta / 86400:.1f}d ago"


def format_runs(records: list[dict]) -> str:
    """Aligned run-record table (id, verdict, reason, age); definitive when empty."""
    if not records:
        return "no runs recorded (run one with `just run <name>`)"
    rows = [
        (
            str(rec.get("record") or rec.get("name", "?")),
            str(rec.get("verdict", "?")),
            str(rec.get("reason") or "-"),
            _age(float(rec.get("recorded_at", 0.0))),
        )
        for rec in records
    ]
    widths = [max(len(row[i]) for row in rows) for i in range(3)]
    return "\n".join(
        f"{row[0]:<{widths[0]}}  {row[1]:<{widths[1]}}  {row[2]:<{widths[2]}}  {row[3]}"
        for row in rows
    )


def resolve_wait_target(log_dir: Path) -> tuple[str, dict]:
    """What should `wait run` wait on right now?

    Precedence: a running e2e cycle (live, or died mid-run - either way the
    cycle is the story and reports.build_status tells it, ABORTED included) >
    an active single run (run.pid alive) > a finished e2e cycle newer than
    the newest run record (the aggregate block, not one scenario's record) >
    the newest record > nothing.
    """
    state_path = log_dir / "e2e_state.json"
    state: dict | None
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state_mtime = state_path.stat().st_mtime
    except (OSError, json.JSONDecodeError):
        state, state_mtime = None, 0.0
    if not isinstance(state, dict):
        state, state_mtime = None, 0.0
    if state is not None and state.get("status") == "running":
        return "e2e", state
    if reports.pid_alive(log_dir / "run.pid") is True:
        return "run", {}
    recs = list_run_records(log_dir / "runs", limit=1)
    if state is not None and (not recs or state_mtime >= float(recs[0].get("recorded_at", 0.0))):
        return "e2e", state
    if recs:
        return "record", recs[0]
    return "none", {}


def supervise(
    argv: list[str],
    name: str,
    *,
    deadline_s: float = 300.0,
    silence_s: float = 90.0,
    log_path: Path,
    cwd: Path,
    poll_s: float = 1.0,
    heartbeat_path: Path | None = None,
    pid_path: Path | None = None,
) -> tuple[int | None, str | None]:
    """Run argv bounded. Returns (returncode, None) on self-exit or
    (None, reason) after killing a wedged child. reason in
    {"deadline_exceeded", "log_silent"}. Always removes pid_path; leaves the
    last heartbeat for post-mortem."""
    heartbeat_path = heartbeat_path or HEARTBEAT
    pid_path = pid_path or RUN_PID
    heartbeat_path.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.Popen(argv, cwd=str(cwd))
    pid_path.write_text(str(proc.pid), encoding="utf-8")
    start = time.monotonic()
    offset = log_path.stat().st_size if log_path.exists() else 0
    last_growth = time.monotonic()
    tail: list[str] = []
    wall_last_event: float | None = None
    t_first: float | None = None
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
                if t_first is None:
                    for ln in new:
                        t = parse_logfmt(ln).get("t")
                        if isinstance(t, float):
                            t_first = t
                            break
                tail = (tail + new)[-400:]
            hb = derive_heartbeat(tail, time.time(), wall_last_event)
            hb["scenario"] = name
            hb["t_start"] = 0.0 if t_first is None else t_first
            heartbeat_path.write_text(format_heartbeat(hb) + "\n", encoding="utf-8")
            if rc is not None:
                return rc, None
            if time.monotonic() - start > deadline_s:
                _kill(proc)
                return None, "deadline_exceeded"
            if time.monotonic() - last_growth > silence_s:
                _kill(proc)
                return None, "log_silent"
            time.sleep(poll_s)
    finally:
        pid_path.unlink(missing_ok=True)


def _kill(proc: subprocess.Popen) -> None:
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)
