"""Single source of truth for vehicle pose.

Reads PX4's estimated VehicleLocalPosition (sim and hardware alike), anchors it
at takeoff, and publishes takeoff-anchored ENU Odometry plus a latched effective
NED setpoint origin. Subscribes to PX4's versioned `/fmu/out/vehicle_local_position_v1`
directly; sim and hardware both run PX4 v1.17 over uXRCE-DDS and publish it identically.

An optional `/drone/pose_override` (PoseStamped, e.g. from marker_localizer) is
applied to the published ENU pose when it is fresh (within `override_timeout_s`)
and close to the dead-reckoned estimate (within `override_max_jump_m`). This is
the relocalization hook: a known-marker fix nudges the SoT pose without letting
a bad fix teleport the vehicle.

=============================================================================
ROS 2 Interface
Subscriptions:
    /fmu/out/vehicle_local_position_v1  [px4_msgs/VehicleLocalPosition]
    /drone/pose_override  [geometry_msgs/PoseStamped]  — optional relocalization fix
Publishers:
    /drone/odom          [nav_msgs/Odometry]            anchored ENU pose+yaw+twist
    /drone/local_origin  [geometry_msgs/Vector3Stamped] effective NED setpoint origin
=============================================================================
"""

from __future__ import annotations

import math

import rclpy
from geometry_msgs.msg import PoseStamped, Vector3Stamped
from nav_msgs.msg import Odometry
from px4_msgs.msg import VehicleLocalPosition
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy

from ros_px4_template_core.lib.frames import (
    enu_quaternion_from_yaw,
    enu_yaw_from_heading,
    enu_yaw_from_quaternion,
    ned_to_enu,
)
from ros_px4_template_core.lib.px4_local_frame import Px4LocalFrame
from ros_px4_template_core.lib.structured_logger import StructuredLogger

_POSITION_TOPIC = "/fmu/out/vehicle_local_position_v1"

_PX4_QOS = QoSProfile(
    reliability=ReliabilityPolicy.BEST_EFFORT,
    durability=DurabilityPolicy.TRANSIENT_LOCAL,
    history=HistoryPolicy.KEEP_LAST,
    depth=10,
)
_ODOM_QOS = QoSProfile(
    reliability=ReliabilityPolicy.RELIABLE,
    durability=DurabilityPolicy.VOLATILE,
    history=HistoryPolicy.KEEP_LAST,
    depth=10,
)
_LATCHED_QOS = QoSProfile(
    reliability=ReliabilityPolicy.RELIABLE,
    durability=DurabilityPolicy.TRANSIENT_LOCAL,
    history=HistoryPolicy.KEEP_LAST,
    depth=1,
)


class PositionNode(Node):
    """Anchored-ENU single source of truth from PX4's local-position estimate."""

    def __init__(self) -> None:
        super().__init__("position_node")
        self.declare_parameter("frame_id", "map")
        self.declare_parameter("child_frame_id", "base_link")
        self.declare_parameter("log_dir", "./logs")
        self.declare_parameter("override_timeout_s", 0.5)
        self.declare_parameter("override_max_jump_m", 10.0)

        self._topic = _POSITION_TOPIC
        self._frame_id = str(self.get_parameter("frame_id").value)
        self._child_frame_id = str(self.get_parameter("child_frame_id").value)
        self._override_timeout_s = float(self.get_parameter("override_timeout_s").value)
        self._override_max_jump_m = float(self.get_parameter("override_max_jump_m").value)
        self.slog = StructuredLogger(self)

        self._frame = Px4LocalFrame()
        self._have_pose = False
        self._override: tuple[float, float, float, float] | None = None
        self._override_time = 0.0

        self.create_subscription(VehicleLocalPosition, self._topic, self._position_cb, _PX4_QOS)
        self.create_subscription(PoseStamped, "/drone/pose_override", self._override_cb, _ODOM_QOS)
        self._pub_odom = self.create_publisher(Odometry, "/drone/odom", _ODOM_QOS)
        self._pub_origin = self.create_publisher(
            Vector3Stamped, "/drone/local_origin", _LATCHED_QOS
        )
        self.slog.info("position_node ready", topic=self._topic)

    def _override_cb(self, msg: PoseStamped) -> None:
        p = msg.pose.position
        q = msg.pose.orientation
        yaw = enu_yaw_from_quaternion(q.w, q.x, q.y, q.z)
        self._override = (float(p.x), float(p.y), float(p.z), float(yaw))
        self._override_time = self.get_clock().now().nanoseconds * 1e-9

    def _position_cb(self, msg: VehicleLocalPosition) -> None:
        if not (msg.xy_valid and msg.z_valid):
            return
        x_enu, y_enu, z_enu = self._frame.observe(
            float(msg.x),
            float(msg.y),
            float(msg.z),
            z_global=bool(msg.z_global),
            xy_reset_counter=int(msg.xy_reset_counter),
            delta_x=float(msg.delta_xy[0]),
            delta_y=float(msg.delta_xy[1]),
            z_reset_counter=int(msg.z_reset_counter),
            delta_z=float(msg.delta_z),
        )
        yaw_enu = enu_yaw_from_heading(float(msg.heading))

        if self._override is not None:
            now_s = self.get_clock().now().nanoseconds * 1e-9
            if now_s - self._override_time <= self._override_timeout_s:
                ox, oy, oz, oyaw = self._override
                if math.dist((ox, oy, oz), (x_enu, y_enu, z_enu)) <= self._override_max_jump_m:
                    x_enu, y_enu, z_enu, yaw_enu = ox, oy, oz, oyaw
                else:
                    self.slog.warn(
                        "pose_override rejected (jump too large)",
                        ox=ox,
                        oy=oy,
                        oz=oz,
                        x=x_enu,
                        y=y_enu,
                        z=z_enu,
                    )

        stamp = self.get_clock().now().to_msg()

        odom = Odometry()
        odom.header.stamp = stamp
        odom.header.frame_id = self._frame_id
        odom.child_frame_id = self._child_frame_id
        odom.pose.pose.position.x = x_enu
        odom.pose.pose.position.y = y_enu
        odom.pose.pose.position.z = z_enu
        qw, qx, qy, qz = enu_quaternion_from_yaw(yaw_enu)
        odom.pose.pose.orientation.w = qw
        odom.pose.pose.orientation.x = qx
        odom.pose.pose.orientation.y = qy
        odom.pose.pose.orientation.z = qz
        # PX4 velocity is NED; ned_to_enu maps it to ENU (vx_enu=ve, vy_enu=vn, vz_enu=-vd).
        vx_enu, vy_enu, vz_enu = ned_to_enu(float(msg.vx), float(msg.vy), float(msg.vz))
        odom.twist.twist.linear.x = vx_enu
        odom.twist.twist.linear.y = vy_enu
        odom.twist.twist.linear.z = vz_enu
        self._pub_odom.publish(odom)

        ox2, oy2, oz2 = self._frame.setpoint_origin_ned
        origin = Vector3Stamped()
        origin.header.stamp = stamp
        origin.header.frame_id = self._frame_id
        origin.vector.x = ox2
        origin.vector.y = oy2
        origin.vector.z = oz2
        self._pub_origin.publish(origin)

        if not self._have_pose:
            self._have_pose = True
            self.slog.info("First pose published", x=x_enu, y=y_enu, z=z_enu)

    def destroy_node(self) -> None:
        self.slog.close()
        super().destroy_node()


def main(args: list[str] | None = None) -> None:
    rclpy.init(args=args)
    node = PositionNode()
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
