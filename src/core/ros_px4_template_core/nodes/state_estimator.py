"""State estimator node (stub).

Subscribes to PX4 odometry and logs via StructuredLogger. No TF or fusion yet —
add your EKF here when you need it.

=============================================================================
ROS 2 Interface
=============================================================================

Subscriptions:
    /fmu/out/vehicle_local_position

Publishers:
    (none — TODO: /tf via tf2 when fusion is implemented)
=============================================================================
"""

from __future__ import annotations

import rclpy
from px4_msgs.msg import VehicleLocalPosition
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy

from ros_px4_template_core.lib.structured_logger import StructuredLogger

_PX4_QOS = QoSProfile(
    reliability=ReliabilityPolicy.BEST_EFFORT,
    durability=DurabilityPolicy.TRANSIENT_LOCAL,
    history=HistoryPolicy.KEEP_LAST,
    depth=10,
)


class StateEstimator(Node):
    """Logs ENU-converted position from PX4 (TF publishing: TODO)."""

    def __init__(self) -> None:
        super().__init__("state_estimator")
        self.declare_parameter("log_dir", "./logs")
        log_dir = str(self.get_parameter("log_dir").value)
        self.slog = StructuredLogger(self, log_dir=log_dir)
        self.create_subscription(
            VehicleLocalPosition,
            "/fmu/out/vehicle_local_position",
            self._position_cb,
            _PX4_QOS,
        )
        self.slog.info("StateEstimator ready")

    def _position_cb(self, msg: VehicleLocalPosition) -> None:
        # Position is available via MCP /fmu/out/* — do not log every odom sample.
        _ = msg

    def destroy_node(self) -> None:
        self.slog.close()
        super().destroy_node()


def main(args: list[str] | None = None) -> None:
    rclpy.init(args=args)
    node = StateEstimator()
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
