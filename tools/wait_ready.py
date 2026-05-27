#!/usr/bin/env python3
"""Block until the full sim stack is ready for agent use.

Readiness criteria (both must pass):
  1. rosbridge WebSocket port 9090 is open.
  2. /fmu/out/vehicle_local_position appears in `ros2 topic list`
     (confirms PX4 SITL + MicroXRCEAgent + px4_topic_relay are all up).

Exit 0 on ready, 1 on timeout.
"""

from __future__ import annotations

import socket
import subprocess
import sys
import time

import typer

app = typer.Typer()

_ROSBRIDGE_PORT = 9090
_REQUIRED_TOPIC = "/fmu/out/vehicle_local_position"
_POLL_INTERVAL_S = 3.0


def _port_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1.0):
            return True
    except OSError:
        return False


def _topic_live(topic: str) -> bool:
    try:
        result = subprocess.run(
            ["ros2", "topic", "list"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return topic in result.stdout.splitlines()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


@app.command()
def main(timeout: int = typer.Option(180, "--timeout", help="Seconds before giving up")) -> None:
    deadline = time.monotonic() + timeout
    typer.echo(f"Waiting for sim stack (timeout {timeout}s)...")

    rosbridge_ok = False
    topic_ok = False

    while time.monotonic() < deadline:
        if not rosbridge_ok:
            rosbridge_ok = _port_open(_ROSBRIDGE_PORT)
            if rosbridge_ok:
                typer.echo("  [OK] rosbridge :9090 open")

        if not topic_ok:
            topic_ok = _topic_live(_REQUIRED_TOPIC)
            if topic_ok:
                typer.echo(f"  [OK] {_REQUIRED_TOPIC} live")

        if rosbridge_ok and topic_ok:
            typer.echo("Stack ready.")
            raise typer.Exit(0)

        remaining = int(deadline - time.monotonic())
        typer.echo(
            f"  waiting... rosbridge={'OK' if rosbridge_ok else '...'} "
            f"topic={'OK' if topic_ok else '...'} ({remaining}s left)"
        )
        time.sleep(_POLL_INTERVAL_S)

    typer.echo(
        f"TIMEOUT after {timeout}s — rosbridge={rosbridge_ok} topic={topic_ok}",
        err=True,
    )
    sys.exit(1)


if __name__ == "__main__":
    app()
