#!/usr/bin/env python3
# tools/fault_inject.py
"""Fault injection node for sim testing.

Subscribes to /fmu/out/vehicle_local_position, applies a configurable
disturbance for --duration seconds, then passes through unchanged.

Publishes distorted messages to /fault/vehicle_local_position.

Usage:
    uv run tools/fault_inject.py --fault gps_dropout --duration 5
    uv run tools/fault_inject.py --fault position_noise --sigma 2.0 --duration 10
    uv run tools/fault_inject.py --fault altitude_spike --spike 5.0 --duration 3
"""

from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

sys.path.insert(
    0,
    str(
        Path(__file__).resolve().parents[1]
        / "install"
        / "ros_px4_template_core"
        / "lib"
        / "python3.12"
        / "site-packages"
    ),
)

import rclpy
from px4_msgs.msg import VehicleLocalPosition
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
from ros_px4_template_core.lib.fault_transforms import (
    apply_altitude_spike,
    apply_gps_dropout,
    apply_position_noise,
)

_PX4_QOS = QoSProfile(
    reliability=ReliabilityPolicy.BEST_EFFORT,
    durability=DurabilityPolicy.TRANSIENT_LOCAL,
    history=HistoryPolicy.KEEP_LAST,
    depth=10,
)


class FaultInjector(Node):
    def __init__(self, fault_type: str, duration_s: float, sigma_m: float, spike_m: float) -> None:
        super().__init__("fault_injector")
        self._fault_type = fault_type
        self._duration_s = duration_s
        self._sigma_m = sigma_m
        self._spike_m = spike_m
        self._start: float | None = None

        self.create_subscription(
            VehicleLocalPosition,
            "/fmu/out/vehicle_local_position",
            self._cb,
            _PX4_QOS,
        )
        self._pub = self.create_publisher(
            VehicleLocalPosition,
            "/fault/vehicle_local_position",
            _PX4_QOS,
        )
        self.get_logger().info(f"FaultInjector active: {fault_type} for {duration_s}s")

    def _cb(self, msg: VehicleLocalPosition) -> None:
        now = self.get_clock().now().nanoseconds / 1e9
        if self._start is None:
            self._start = now
            self.get_logger().info("First message received, starting fault injection timer.")

        elapsed = now - self._start

        if elapsed > self._duration_s:
            self._pub.publish(msg)
            return

        if self._fault_type == "gps_dropout":
            ok, ok_z, x, y, z = apply_gps_dropout(msg.xy_valid, msg.z_valid, msg.x, msg.y, msg.z)
        elif self._fault_type == "position_noise":
            ok, ok_z, x, y, z = apply_position_noise(
                msg.xy_valid,
                msg.z_valid,
                msg.x,
                msg.y,
                msg.z,
                self._sigma_m,
                random.gauss(0, 1),
                random.gauss(0, 1),
            )
        elif self._fault_type == "altitude_spike":
            ok, ok_z, x, y, z = apply_altitude_spike(
                msg.xy_valid, msg.z_valid, msg.x, msg.y, msg.z, self._spike_m
            )
        else:
            self._pub.publish(msg)
            return

        msg.xy_valid = ok
        msg.z_valid = ok_z
        msg.x = x
        msg.y = y
        msg.z = z
        self._pub.publish(msg)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--fault",
        choices=["gps_dropout", "position_noise", "altitude_spike"],
        required=True,
    )
    parser.add_argument("--duration", type=float, default=5.0)
    parser.add_argument("--sigma", type=float, default=2.0)
    parser.add_argument("--spike", type=float, default=5.0)
    args = parser.parse_args()

    rclpy.init()
    node = FaultInjector(args.fault, args.duration, args.sigma, args.spike)
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
