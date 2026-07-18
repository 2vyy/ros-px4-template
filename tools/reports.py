#!/usr/bin/env python3
"""Verdicts from logs/ artifacts: per-scenario, e2e aggregate, e2e progress.

Reads logs/scenario_*.json and logs/e2e_state.json; speaks concise English
via cli_verdict. Exit-code contracts unchanged: build_block 0 all-pass / 1;
build_status 0 finished-all-pass, 1 finished-with-failures-or-died, 2 no run,
3 running. (Per-scenario verdict lines live on in run records via `just runs`.)
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from cli_verdict import ExitCode, format_e2e_block

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
