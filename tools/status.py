#!/usr/bin/env python3
"""Compact sim/stack status snapshot for agents.

Concise English workspace snapshot (nodes, live status, capabilities).
Exit 0 always — meant as a read-only diagnostic, not a gating check.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from probes import port_open as _port_open

LOG_DIR = Path(__file__).resolve().parents[1] / "logs"


def _get_nodes_via_ws(port: int = 9090, timeout: float = 1.0) -> list[str] | None:
    from probes import rosapi_call

    return rosapi_call("/rosapi/nodes", "nodes", port=port, timeout=timeout, req_id="status_nodes")


def _ros_nodes() -> list[str] | None:
    # Try WebSocket query first to avoid expensive subprocess and host-side ROS sourcing requirements
    ws_nodes = _get_nodes_via_ws()
    if ws_nodes is not None:
        return sorted(ws_nodes)

    try:
        r = subprocess.run(
            ["ros2", "node", "list"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if r.returncode == 0:
            return sorted(n for n in r.stdout.splitlines() if n.strip())
        return None
    except Exception:
        return None


def _scenarios() -> list[dict]:
    results = []
    for f in sorted(LOG_DIR.glob("scenario_*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            results.append(
                {
                    "name": data["scenario"],
                    "passed": data["passed"],
                    "elapsed_s": data["elapsed_s"],
                }
            )
        except Exception:
            pass
    return results


def _last_event() -> dict | None:
    summary_f = LOG_DIR / "latest_summary.json"
    if not summary_f.exists():
        return None
    try:
        s = json.loads(summary_f.read_text(encoding="utf-8"))
        tl = s.get("event_timeline", [])
        return tl[-1] if tl else None
    except Exception:
        return None


def format_status(
    *,
    sim_alive: bool,
    nodes: list[str] | None,
    scenarios: list[dict],
    last_event: dict | None,
    ros_env_error: str | None,
) -> str:
    """Concise English snapshot of the running stack (no JSON)."""
    lines: list[str] = []
    if sim_alive:
        n = len(nodes) if nodes else 0
        lines.append(f"stack: UP ({n} nodes)")
        if nodes:
            lines.append("  nodes: " + ", ".join(sorted(nodes)))
    else:
        lines.append("stack: DOWN")

    if scenarios:
        for s in scenarios:
            tag = "PASS" if s.get("passed") else "FAIL"
            lines.append(f"  {tag} {s['name']} ({s.get('elapsed_s')}s)")
    if last_event:
        lines.append(
            f"  last event: t={last_event.get('t')} "
            f"{last_event.get('event')} ({last_event.get('node')})"
        )
    if ros_env_error:
        lines.append(f"  ! {ros_env_error}")

    hints: list[str] = []
    if not sim_alive:
        hints.append("just sim start")
    if not scenarios:
        hints.append("just e2e")
    if hints:
        lines.append("  hint: " + " ; ".join(hints))
    return "\n".join(lines)


def main() -> None:
    sim_alive = _port_open(9090)
    ros2_on_path = bool(shutil.which("ros2"))
    nodes = _ros_nodes() if sim_alive else None
    scenarios = _scenarios()
    ros_env_error = (
        None
        if ros2_on_path
        else "ros2 not on PATH — source ROS_SETUP (or enter distrobox) before running"
    )
    print(
        format_status(
            sim_alive=sim_alive,
            nodes=nodes,
            scenarios=scenarios,
            last_event=_last_event(),
            ros_env_error=ros_env_error,
        )
    )


if __name__ == "__main__":
    main()
