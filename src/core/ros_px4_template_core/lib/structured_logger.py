"""Structured JSONL logging alongside ROS 2 logging."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Protocol


class _NodeLike(Protocol):
    """ROS node surface used by StructuredLogger (no rclpy import in lib/)."""

    def get_name(self) -> str: ...

    def get_logger(self): ...

    def get_clock(self): ...


class StructuredLogger:
    """Writes structured JSONL logs for agent-friendly debugging."""

    def __init__(self, node: _NodeLike, log_dir: str = "./logs") -> None:
        self._node = node
        self._log_dir = Path(log_dir)
        self._log_dir.mkdir(parents=True, exist_ok=True)
        log_path = self._log_dir / f"{node.get_name()}.jsonl"
        self._file = log_path.open("a", encoding="utf-8", buffering=1)
        self._throttle_state: dict[str, float] = {}

    def _emit(self, level: str, msg: str, **fields: Any) -> None:
        record = {
            "ts": time.time(),
            "ros_ts": self._node.get_clock().now().nanoseconds / 1e9,
            "node": self._node.get_name(),
            "level": level,
            "msg": msg,
            **fields,
        }
        self._file.write(json.dumps(record) + "\n")

    def info(self, msg: str, **fields: Any) -> None:
        self._node.get_logger().info(msg)
        self._emit("INFO", msg, **fields)

    def warn(self, msg: str, **fields: Any) -> None:
        self._node.get_logger().warn(msg)
        self._emit("WARN", msg, **fields)

    def error(self, msg: str, **fields: Any) -> None:
        self._node.get_logger().error(msg)
        self._emit("ERROR", msg, **fields)

    def info_throttled(self, msg: str, key: str, interval_s: float = 1.0, **fields: Any) -> None:
        """Like info() but suppresses repeats within interval_s (use in tight loops)."""
        now = time.time()
        last = self._throttle_state.get(key, 0.0)
        if now - last >= interval_s:
            self._throttle_state[key] = now
            self.info(msg, **fields)

    def warn_throttled(self, msg: str, key: str, interval_s: float = 1.0, **fields: Any) -> None:
        """Like warn() but suppresses repeats within interval_s."""
        now = time.time()
        last = self._throttle_state.get(key, 0.0)
        if now - last >= interval_s:
            self._throttle_state[key] = now
            self.warn(msg, **fields)

    def event(self, event: str, **fields: Any) -> None:
        """Named moment for agents — JSONL only, no ROS logger line."""
        self._emit("EVENT", event, **fields)

    def close(self) -> None:
        self._file.close()
