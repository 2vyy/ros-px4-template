#!/usr/bin/env python3
"""Shared local-stack probes: TCP port checks and rosbridge /rosapi calls."""

from __future__ import annotations

import json
import socket
import time


def port_open(port: int, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except OSError:
        return False


def rosapi_call(
    service: str, result_key: str, *, port: int = 9090, timeout: float = 1.0, req_id: str = "probe"
) -> list[str] | None:
    """Call a /rosapi service over the rosbridge WebSocket; None on any failure."""
    try:
        import websocket  # type: ignore[import-untyped]

        ws = websocket.create_connection(f"ws://127.0.0.1:{port}", timeout=timeout)
        ws.send(json.dumps({"op": "call_service", "service": service, "id": req_id}))
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            msg = json.loads(ws.recv())
            if msg.get("op") == "service_response" and msg.get("service") == service:
                ws.close()
                return msg.get("values", {}).get(result_key, [])
        ws.close()
    except Exception:
        pass
    return None
