#!/usr/bin/env python3
"""Benchmark cold-start time: sim launch → drone first vertical movement.

Records wall-clock milestones:
  t0          : sim bg launched (this script's reference zero)
  t_xrce      : first VehicleLocalPosition received (XRCE bridge alive)
  t_arm       : arming_state == ARMED
  t_move      : z_enu first crosses 0.05 m (clearly moving up)

Usage (inside distrobox with ROS sourced):
  uv run python tools/benchmark_startup.py [--runs N] [--no-stop]
"""

from __future__ import annotations

import argparse
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _run_one(run_idx: int, stop_first: bool) -> dict[str, float] | None:
    print(f"\n{'=' * 60}")
    print(f"Run {run_idx + 1}")
    print(f"{'=' * 60}")

    if stop_first:
        print("Stopping any running sim...", flush=True)
        subprocess.run(
            ["uv", "run", "python", "tools/sim_cleanup.py"],
            cwd=str(ROOT),
            capture_output=True,
        )
        time.sleep(0.5)

    t0 = time.monotonic()
    print(f"[T+{0:.2f}s] Launching sim bg...", flush=True)

    subprocess.Popen(
        ["uv", "run", "python", "tasks.py", "sim", "bg"],
        cwd=str(ROOT),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # Delay ROS init so the Popen above returns before we block on rclpy
    time.sleep(0.1)

    import rclpy
    from px4_msgs.msg import VehicleLocalPosition, VehicleStatus
    from rclpy.node import Node
    from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy

    try:
        from ros_px4_template_core.lib.frame_transforms import ned_to_enu
    except ImportError:

        def ned_to_enu(x, y, z):  # type: ignore[misc]
            return y, x, -z

    PX4_QOS = QoSProfile(
        reliability=ReliabilityPolicy.BEST_EFFORT,
        durability=DurabilityPolicy.VOLATILE,
        history=HistoryPolicy.KEEP_LAST,
        depth=10,
    )

    milestones: dict[str, float] = {}

    class _Monitor(Node):
        def __init__(self) -> None:
            super().__init__("benchmark_startup")
            self.z_enu = 0.0
            self.create_subscription(
                VehicleLocalPosition,
                "/fmu/out/vehicle_local_position",
                self._pos_cb,
                PX4_QOS,
            )
            self.create_subscription(
                VehicleStatus,
                "/fmu/out/vehicle_status",
                self._status_cb,
                PX4_QOS,
            )
            self.create_timer(0.05, self._tick)

        def _pos_cb(self, msg: VehicleLocalPosition) -> None:
            _, _, self.z_enu = ned_to_enu(msg.x, msg.y, msg.z)
            if "t_xrce" not in milestones:
                milestones["t_xrce"] = time.monotonic() - t0
                print(
                    f"[T+{milestones['t_xrce']:.2f}s] XRCE connected (first position msg)",
                    flush=True,
                )

        def _status_cb(self, msg: VehicleStatus) -> None:
            if "t_arm" not in milestones and msg.arming_state == 2:
                milestones["t_arm"] = time.monotonic() - t0
                print(f"[T+{milestones['t_arm']:.2f}s] ARMED", flush=True)

        def _tick(self) -> None:
            elapsed = time.monotonic() - t0
            if elapsed > 3 and elapsed % 5 < 0.06:
                print(f"[T+{elapsed:.1f}s] waiting... z={self.z_enu:.3f}m", flush=True)
            if "t_arm" in milestones and "t_move" not in milestones and self.z_enu > 0.05:
                milestones["t_move"] = time.monotonic() - t0
                print(
                    f"[T+{milestones['t_move']:.2f}s] FIRST VERTICAL MOVEMENT (z={self.z_enu:.3f}m)",
                    flush=True,
                )
                raise SystemExit(0)
            if elapsed > 180:
                print(f"[T+{elapsed:.0f}s] TIMEOUT", flush=True)
                raise SystemExit(1)

    rclpy.init()
    node = _Monitor()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()

    return milestones if milestones else None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--no-stop", action="store_true", help="Skip sim stop before launch")
    args = ap.parse_args()

    results: list[dict[str, float]] = []

    for i in range(args.runs):
        m = _run_one(i, stop_first=not args.no_stop)
        if m:
            results.append(m)
            if args.runs > 1 and i < args.runs - 1:
                print("Stopping sim for next run...", flush=True)
                subprocess.run(
                    ["uv", "run", "python", "tools/sim_cleanup.py"],
                    cwd=str(ROOT),
                    capture_output=True,
                )
                time.sleep(1.0)

    print(f"\n{'=' * 60}")
    print("BENCHMARK RESULTS")
    print(f"{'=' * 60}")
    keys = ["t_xrce", "t_arm", "t_move"]
    labels = {
        "t_xrce": "XRCE connected (first pos msg)",
        "t_arm": "Armed",
        "t_move": "First vertical movement",
    }
    for r in results:
        for k in keys:
            if k in r:
                print(f"  {labels[k]:<35} {r[k]:.2f}s")
        print()

    if len(results) > 1:
        print("Averages:")
        for k in keys:
            vals = [r[k] for r in results if k in r]
            if vals:
                print(f"  {labels[k]:<35} {sum(vals) / len(vals):.2f}s (n={len(vals)})")


if __name__ == "__main__":
    main()
