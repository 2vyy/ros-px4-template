#!/usr/bin/env python3
"""Block until the full sim stack is ready for agent use.

Readiness criteria (all three must pass):
  1. /fmu/out/vehicle_local_position_v1 appears in `ros2 topic list`
     (confirms PX4 SITL + MicroXRCEAgent are up and publishing telemetry).
  2. rosbridge WebSocket port 9090 is open.
  3. gcs_heartbeat has committed PX4 params (a FRESH /tmp/gcs_params_flag,
     mtime at/after this waiter started), confirming the MAVLink GCS link is
     established and PX4 is responsive. The freshness check stops a flag left
     behind by an unclean exit from false-READYing a new boot.

Exit 0 on ready, 1 on timeout.
"""

from __future__ import annotations

import json
import os
import shlex
import socket
import subprocess
import sys
import time
from pathlib import Path

import typer

app = typer.Typer()

_ROSBRIDGE_PORT = 9090
_REQUIRED_TOPIC = "/fmu/out/vehicle_local_position_v1"

_POLL_INTERVAL_S = 0.5
_GCS_PARAMS_FLAG = Path("/tmp/gcs_params_flag")
_ROOT = Path(__file__).resolve().parents[1]


def _port_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1.0):
            return True
    except OSError:
        return False


def _rosbridge_ws_ok(port: int = _ROSBRIDGE_PORT) -> bool:
    """True if rosbridge accepts a WebSocket connection (Jazzy has no op:topics)."""
    if not _port_open(port):
        return False
    try:
        import websocket  # type: ignore[import-untyped]
    except ImportError:
        return _port_open(port)
    try:
        ws = websocket.create_connection(f"ws://127.0.0.1:{port}", timeout=3)
        ws.close()
        return True
    except Exception:
        return False


def _ros2_topic_list_argv() -> list[str]:
    """``bash -lc`` that sources ROS + workspace, then ``ros2 topic list``."""
    ros_setup = os.environ.get("ROS_SETUP", "/opt/ros/jazzy/setup.bash")
    ws_setup = _ROOT / "install" / "setup.bash"
    sources = [f"source {shlex.quote(ros_setup)}"]
    if ws_setup.exists():
        sources.append(f"source {shlex.quote(str(ws_setup))}")
    inner = " && ".join([*sources, "ros2 topic list"])
    return ["bash", "-lc", inner]


def _get_topics_via_ws(port: int = _ROSBRIDGE_PORT, timeout: float = 1.0) -> list[str] | None:
    try:
        import websocket  # type: ignore[import-untyped]

        ws = websocket.create_connection(f"ws://127.0.0.1:{port}", timeout=timeout)
        req = {"op": "call_service", "service": "/rosapi/topics", "id": "wait_ready_topics"}
        ws.send(json.dumps(req))
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            msg = json.loads(ws.recv())
            if msg.get("op") == "service_response" and msg.get("service") == "/rosapi/topics":
                ws.close()
                return msg.get("values", {}).get("topics", [])
        ws.close()
    except Exception:
        pass
    return None


def _topic_live(topic: str) -> bool:
    # Try WebSocket query first to avoid expensive subprocess and host-side ROS sourcing requirements
    ws_topics = _get_topics_via_ws()
    if ws_topics is not None:
        return topic in ws_topics

    try:
        result = subprocess.run(
            _ros2_topic_list_argv(),
            capture_output=True,
            text=True,
            timeout=15,
            cwd=str(_ROOT),
        )
        return topic in result.stdout.splitlines()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def _px4_standby(not_before: float) -> bool:
    """Return True if gcs_heartbeat wrote a FRESH params-committed flag.

    Fresh = flag mtime at/after ``not_before`` (this waiter's start), so a flag
    left behind by a previous session's unclean exit never false-READYs this
    boot. The flag is written by gcs_heartbeat when PX4 acknowledges a Params
    committed event; it persists through arm transitions, unlike arming_state
    DDS polling. sim_cleanup normally deletes it on stop; the mtime gate covers
    the case where an unclean exit left it behind.
    """
    try:
        return _GCS_PARAMS_FLAG.stat().st_mtime >= not_before
    except FileNotFoundError:
        return False


@app.command()
def main(
    timeout: int = typer.Option(180, "--timeout", help="Seconds before giving up"),
) -> None:
    deadline = time.monotonic() + timeout
    # Wall-clock reference for the params-flag freshness gate (mtime is wall clock).
    # wait_ready is invoked after the stack spawns, so this session's flag is always
    # written later; a flag from a previous session is older and correctly rejected.
    not_before = time.time()
    typer.echo(f"Waiting for sim stack (timeout {timeout}s)...")

    rosbridge_ok = False
    topic_ok = False
    standby_ok = False

    while time.monotonic() < deadline:
        if not topic_ok:
            topic_ok = _topic_live(_REQUIRED_TOPIC)
            if topic_ok:
                typer.echo(f"  [OK] {_REQUIRED_TOPIC} live")

        if not rosbridge_ok:
            rosbridge_ok = _rosbridge_ws_ok(_ROSBRIDGE_PORT)
            if rosbridge_ok:
                typer.echo("  [OK] rosbridge :9090 WebSocket responding")

        if not standby_ok:
            standby_ok = _px4_standby(not_before)
            if standby_ok:
                typer.echo("  [OK] GCS params committed (PX4 ready)")

        if rosbridge_ok and topic_ok and standby_ok:
            # NEVER call the gz set_physics service here (or anywhere on a running
            # stack). Verified 2026-07-11 (plans/065 spike): ANY set_physics call,
            # even with values identical to the running physics and issued pre-arm
            # on a grounded vehicle, latently corrupts PX4's altitude estimate: z
            # runs away to kilometers once the vehicle arms. Physics comes solely
            # from the world SDF at boot.
            typer.echo("  [OK] Physics at realtime (world SDF defaults)")
            typer.echo("Stack ready.")
            raise typer.Exit(0)

        time.sleep(_POLL_INTERVAL_S)
    typer.echo(
        f"TIMEOUT after {timeout}s — topic={topic_ok} rosbridge={rosbridge_ok} standby={standby_ok}",
        err=True,
    )
    sys.exit(1)


if __name__ == "__main__":
    app()
