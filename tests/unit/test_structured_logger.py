"""Unit tests for StructuredLogger throttle (no rclpy)."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

from ros_px4_template_core.lib.structured_logger import StructuredLogger


def _mock_node(name: str = "test_node") -> MagicMock:
    node = MagicMock()
    node.get_name.return_value = name
    clock = MagicMock()
    clock.now.return_value.nanoseconds = 1_000_000_000
    node.get_clock.return_value = clock
    return node


def test_event_jsonl_only() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        node = _mock_node()
        slog = StructuredLogger(node, log_dir=tmp)
        slog.event("PHASE_CHANGE", **{"from": "a", "to": "b"})
        slog.close()
        record = json.loads(Path(tmp, "test_node.jsonl").read_text().strip())
        assert record["level"] == "EVENT"
        assert record["msg"] == "PHASE_CHANGE"
        node.get_logger().info.assert_not_called()
