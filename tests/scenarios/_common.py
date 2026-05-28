"""Shared helpers for live scenario scripts (not pytest)."""

from __future__ import annotations

import abc
import asyncio
import json
import sys
import time
from collections.abc import Callable
from pathlib import Path

import rclpy
from rclpy.executors import SingleThreadedExecutor
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy

# Matches PX4 uXRCE-DDS publisher QoS (rmw_qos_profile_sensor_data).
PX4_QOS = QoSProfile(
    reliability=ReliabilityPolicy.BEST_EFFORT,
    durability=DurabilityPolicy.VOLATILE,
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


class Scenario(abc.ABC):
    """Minimal base for single-predicate scenarios.

    Subclass and override ``make_node``, ``done``, optionally ``fail_reason`` and
    ``report_detail``. Handles rclpy init/teardown, timeout, exception capture, and
    writes ``logs/scenario_<name>.json`` on every exit path (no silent drops).

    Multi-stage scenarios with intermediate console feedback can keep the
    procedural style in ``run()`` — this is for the common single-predicate case.
    """

    name: str
    timeout_s: float = 60.0

    @abc.abstractmethod
    def make_node(self) -> Node:
        """Return the scenario's subscriber node (called after rclpy.init)."""

    @abc.abstractmethod
    def done(self) -> bool:
        """Return True when the scenario should stop spinning."""

    def fail_reason(self) -> str | None:
        """Return a non-None failure reason to mark the scenario failed despite ``done()``."""
        return None

    def report_detail(self) -> dict:
        """Extra fields to include in the JSON report."""
        return {}

    async def run(self) -> bool:
        rclpy.init()
        started = time.monotonic()
        node: Node | None = None
        try:
            node = self.make_node()
            try:
                await asyncio.wait_for(spin_until(node, self.done), timeout=self.timeout_s)
            except TimeoutError:
                elapsed = time.monotonic() - started
                write_report(
                    self.name, False, elapsed, {"reason": "timeout", **self.report_detail()}
                )
                return False
            elapsed = time.monotonic() - started
            reason = self.fail_reason()
            if reason is not None:
                write_report(self.name, False, elapsed, {"reason": reason, **self.report_detail()})
                return False
            write_report(self.name, True, elapsed, self.report_detail())
            return True
        except Exception as exc:
            elapsed = time.monotonic() - started
            write_report(
                self.name,
                False,
                elapsed,
                {"reason": "exception", "exc": f"{type(exc).__name__}: {exc}"},
            )
            return False
        finally:
            if node is not None:
                node.destroy_node()
            if rclpy.ok():
                rclpy.shutdown()


def run_main(scenario_cls: type[Scenario]) -> None:
    """Entry point helper: ``if __name__ == '__main__': run_main(MyScenario)``."""
    sys.exit(0 if asyncio.run(scenario_cls().run()) else 1)
