#!/usr/bin/env python3
"""Post-run e2e report: scenarios + key log events in ~80 tokens.

Reads logs/latest_summary.json and logs/scenario_*.json.
Exits 1 if any scenario failed or no scenarios found.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

LOG_DIR = Path(__file__).resolve().parents[1] / "logs"
_MAX_EVENTS = 10


def main() -> None:
    scenarios: list[dict] = []
    for f in sorted(LOG_DIR.glob("scenario_*.json")):
        try:
            scenarios.append(json.loads(f.read_text(encoding="utf-8")))
        except Exception:
            pass
    summary_f = LOG_DIR / "latest_summary.json"
    summary: dict = {}
    if summary_f.exists():
        try:
            summary = json.loads(summary_f.read_text(encoding="utf-8"))
        except Exception:
            pass

    if not scenarios and not summary:
        print(json.dumps({"empty": True, "help": ["just e2e", "just merge-logs"]}, indent=2))
        sys.exit(1)

    scenario_rows = [
        {
            "name": s["scenario"],
            "passed": s["passed"],
            "elapsed_s": s.get("elapsed_s"),
        }
        for s in scenarios
    ]
    all_passed = all(s["passed"] for s in scenarios) if scenarios else None

    timeline = summary.get("event_timeline", [])
    key_events = [
        {"t": e["t"], "node": e.get("node"), "event": e.get("event")}
        for e in timeline[-_MAX_EVENTS:]
    ]

    report = {
        "run_id": summary.get("run_id"),
        "duration_s": summary.get("duration_s"),
        "all_passed": all_passed,
        "scenarios": scenario_rows,
        "error_count": summary.get("error_count", 0),
        "last_events": key_events,
    }
    if summary.get("errors"):
        report["errors"] = [
            {"node": e.get("node"), "msg": e.get("msg")} for e in summary["errors"][:5]
        ]

    print(json.dumps(report, indent=2))
    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()
