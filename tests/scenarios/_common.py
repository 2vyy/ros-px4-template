"""Shared helpers for live scenario scripts (not pytest)."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from pathlib import Path

from rclpy.executors import SingleThreadedExecutor
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy

PX4_QOS = QoSProfile(
    reliability=ReliabilityPolicy.BEST_EFFORT,
    durability=DurabilityPolicy.TRANSIENT_LOCAL,
    history=HistoryPolicy.KEEP_LAST,
    depth=10,
)

_LOG_DIR = Path(__file__).resolve().parents[2] / "logs"


async def spin_until(
    node: Node,
    done: Callable[[], bool],
    *,
    poll_s: float = 0.01,
    spin_timeout_s: float = 0.05,
) -> None:
    """Pump rclpy and asyncio until ``done()`` returns True."""
    executor = SingleThreadedExecutor()
    executor.add_node(node)
    try:
        while not done():
            executor.spin_once(timeout_sec=spin_timeout_s)
            await asyncio.sleep(poll_s)
    finally:
        executor.remove_node(node)


def write_report(name: str, passed: bool, elapsed_s: float, detail: dict | None = None) -> None:
    """Write a machine-readable JSON report to logs/scenario_<name>.json."""
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    report = {
        "scenario": name,
        "passed": passed,
        "elapsed_s": round(elapsed_s, 2),
        "detail": detail or {},
    }
    out = _LOG_DIR / f"scenario_{name}.json"
    out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
