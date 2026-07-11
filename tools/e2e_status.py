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
        speed = state.get("speed", 1.0)
        speed_txt = f" at {speed}x" if speed != 1.0 else ""
        latest = log_dir / "latest.log"
        age = f"{time.time() - latest.stat().st_mtime:.0f}s ago" if latest.exists() else "n/a"
        lines = []
        if any(log_dir.glob("scenario_*.json")):
            lines.append(build_block(log_dir)[0])
        lines.append(f"RUNNING {current_txt}{speed_txt}, last activity {age}")
        return ("\n".join(lines), 3)

    if state.get("status") == "aborted":
        return (
            f"e2e ABORTED after group {done}/{len(groups)} (stopped or crashed; see logs/e2e.log)",
            1,
        )

    block, _code = build_block(log_dir)
    code = 0 if state.get("status") == "passed" else 1
    return (block, code)


def main() -> None:
    text, code = build_status(LOG_DIR, _pid_alive(LOG_DIR / "e2e.pid"))
    print(text)
    sys.exit(code)


if __name__ == "__main__":
    main()
