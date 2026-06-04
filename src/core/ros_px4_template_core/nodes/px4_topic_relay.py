"""Relay PX4 v1 uXRCE topics to legacy names used by core nodes."""

from __future__ import annotations

import rclpy
from px4_msgs.msg import VehicleLocalPosition, VehicleStatus
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy

_PX4_QOS = QoSProfile(
    reliability=ReliabilityPolicy.BEST_EFFORT,
    durability=DurabilityPolicy.TRANSIENT_LOCAL,
    history=HistoryPolicy.KEEP_LAST,
    depth=10,
)

_RELAYS: tuple[tuple[type, str, str], ...] = (
    (VehicleLocalPosition, "/fmu/out/vehicle_local_position_v1", "/fmu/out/vehicle_local_position"),
    (VehicleStatus, "/fmu/out/vehicle_status_v1", "/fmu/out/vehicle_status"),
)


class Px4TopicRelay(Node):
    def __init__(self) -> None:
        super().__init__("px4_topic_relay")
        for msg_type, src, dst in _RELAYS:
            pub = self.create_publisher(msg_type, dst, _PX4_QOS)

            def _republish(msg: msg_type, publisher=pub) -> None:
                publisher.publish(msg)

            self.create_subscription(msg_type, src, _republish, _PX4_QOS)
        self.get_logger().info("PX4 v1 topic relay active")


def main() -> None:
    rclpy.init()
    node = Px4TopicRelay()
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
