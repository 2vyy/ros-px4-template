#!/usr/bin/env python3
"""Compact sim/stack status snapshot for agents.

Outputs JSON: sim_alive, live nodes, last scenario results, last log event.
Exit 0 always — meant as a read-only diagnostic, not a gating check.
"""

from __future__ import annotations

import json
import shutil
import socket
import subprocess
from pathlib import Path

LOG_DIR = Path(__file__).resolve().parents[1] / "logs"


def _port_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            return True
    except OSError:
        return False


def _get_nodes_via_ws(port: int = 9090, timeout: float = 1.0) -> list[str] | None:
    try:
        import time

        import websocket  # type: ignore[import-untyped]

        ws = websocket.create_connection(f"ws://127.0.0.1:{port}", timeout=timeout)
        req = {"op": "call_service", "service": "/rosapi/nodes", "id": "status_nodes"}
        ws.send(json.dumps(req))
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            msg = json.loads(ws.recv())
            if msg.get("op") == "service_response" and msg.get("service") == "/rosapi/nodes":
                ws.close()
                return msg.get("values", {}).get("nodes", [])
        ws.close()
    except Exception:
        pass
    return None


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
    summary_f = LOG_DIR / "run_summary.json"
    if not summary_f.exists():
        return None
    try:
        s = json.loads(summary_f.read_text(encoding="utf-8"))
        tl = s.get("event_timeline", [])
        return tl[-1] if tl else None
    except Exception:
        return None


def main() -> None:
    sim_alive = _port_open(9090)
    ros2_on_path = bool(shutil.which("ros2"))
    nodes = _ros_nodes() if sim_alive else None
    scenarios = _scenarios()

    out: dict = {
        "sim_alive": sim_alive,
        "nodes": nodes,
        "scenarios": scenarios if scenarios else None,
        "last_event": _last_event(),
    }

    if not ros2_on_path:
        out["ros_env_error"] = (
            "ros2 not on PATH — source ROS_SETUP (or enter distrobox) before running"
        )

    hints: list[str] = []
    if not sim_alive:
        hints.append("just sim headless  # start sim")
    if not scenarios:
        hints.append("just test e2e  # run all scenarios")
    elif not LOG_DIR.joinpath("run_summary.json").exists():
        hints.append("just log summary  # build event timeline")
    if hints:
        out["help"] = hints

    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
