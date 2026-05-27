"""Shared helpers for live scenario scripts (not pytest)."""

from __future__ import annotations

import asyncio
from collections.abc import Callable

from rclpy.executors import SingleThreadedExecutor
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy

PX4_QOS = QoSProfile(
    reliability=ReliabilityPolicy.BEST_EFFORT,
    durability=DurabilityPolicy.TRANSIENT_LOCAL,
    history=HistoryPolicy.KEEP_LAST,
    depth=10,
)


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
