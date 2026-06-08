#!/usr/bin/env python3
"""Post-run e2e aggregate: one rich verdict line per scenario plus a summary.

Reads logs/scenario_*.json. Speaks concise English (no JSON). Exits 0 if every
scenario passed and at least one ran, else 1.
"""

from __future__ import annotations

import json
import sys
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


def main() -> None:
    block, code = build_block(LOG_DIR)
    print(block)
    sys.exit(code)


if __name__ == "__main__":
    main()
