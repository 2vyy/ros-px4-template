#!/usr/bin/env python3
"""Print one scenario's last verdict from logs/scenario_<name>.json.

`tools/e2e_report.py` formats verdicts across all scenarios at once; this prints
a single run's rich verdict (and exits 0/1/2) so "what happened in that last
run?" needs no jq. Reuses `cli_verdict.format_scenario` + `e2e_report._detail_str`.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from cli_verdict import ExitCode, format_scenario
from e2e_report import _detail_str

_LOG_DIR = Path(__file__).resolve().parents[1] / "logs"


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


def main() -> None:
    name = sys.argv[1] if len(sys.argv) > 1 else None
    line, code = format_scenario_status(_LOG_DIR, name)
    print(line)
    sys.exit(code)


if __name__ == "__main__":
    main()
