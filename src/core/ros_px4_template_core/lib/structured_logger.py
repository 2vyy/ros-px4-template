"""Structured logfmt logging to stdout (captured into logs/latest.log by log_capture).

Each call prints exactly one logfmt line and nothing else: no private files and no
ROS-logger mirror, so a message is emitted once. The capture filter assigns the
``src=`` tag (from the ros2 launch prefix) and relativizes ``t=``; this module emits
an absolute ``t=<epoch>`` so event timing survives capture latency.
"""

from __future__ import annotations

import time
from typing import Any, Protocol


class _NodeLike(Protocol):
    """Minimal ROS node surface used here (no rclpy import in lib/)."""

    def get_clock(self): ...


def _fmt_value(value: Any) -> str:
    text = str(value).replace("\n", "\\n")
    if text == "" or " " in text or "=" in text or '"' in text:
        return '"' + text.replace('"', '\\"') + '"'
    return text


def render_logfmt(
    level: str,
    key: str,
    msg: str,
    sim_t: float | None,
    fields: dict[str, Any],
) -> str:
    """Render one logfmt line: ``t=<epoch> level=.. [sim_t=..] <key>=<msg> k=v ...``."""
    parts = [f"t={time.time():.3f}", f"level={level}"]
    if sim_t is not None:
        parts.append(f"sim_t={sim_t:.3f}")
    parts.append(f"{key}={_fmt_value(msg)}")
    parts.extend(f"{k}={_fmt_value(v)}" for k, v in fields.items())
    return " ".join(parts)


class StructuredLogger:
    """Writes structured logfmt lines to stdout for agent-friendly debugging."""

    def __init__(self, node: _NodeLike) -> None:
        self._node = node

    def _sim_t(self) -> float | None:
        try:
            ns = self._node.get_clock().now().nanoseconds
        except Exception:
            return None
        return ns / 1e9 if ns > 0 else None

    def _emit(self, level: str, key: str, msg: str, fields: dict[str, Any]) -> None:
        print(render_logfmt(level, key, msg, self._sim_t(), fields), flush=True)

    def info(self, msg: str, **fields: Any) -> None:
        self._emit("info", "msg", msg, fields)

    def warn(self, msg: str, **fields: Any) -> None:
        self._emit("warn", "msg", msg, fields)

    def error(self, msg: str, **fields: Any) -> None:
        self._emit("error", "msg", msg, fields)

    def event(self, event: str, **fields: Any) -> None:
        self._emit("info", "event", event, fields)

    def close(self) -> None:
        """Retained no-op: nodes call this from destroy_node()."""
