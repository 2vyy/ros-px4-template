"""Single home for the project's QoS contracts.

ROS 2 QoS incompatibility fails silently (publisher and subscriber simply
never connect), so these profiles are defined once. PX4_QOS matches PX4
uXRCE-DDS publishers (rmw_qos_profile_sensor_data + TRANSIENT_LOCAL).
tests/scenarios/_common.py keeps an intentionally self-contained copy.

Lives in nodes/ rather than lib/: QoS profiles need rclpy.qos, and lib/ is
kept rclpy-free (see lib/ruff.toml) so its unit tests stay sim-blind.
"""

from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy

PX4_QOS = QoSProfile(
    reliability=ReliabilityPolicy.BEST_EFFORT,
    durability=DurabilityPolicy.TRANSIENT_LOCAL,
    history=HistoryPolicy.KEEP_LAST,
    depth=10,
)
RELIABLE_QOS = QoSProfile(
    reliability=ReliabilityPolicy.RELIABLE,
    history=HistoryPolicy.KEEP_LAST,
    depth=10,
)
ODOM_QOS = QoSProfile(  # /drone/odom: reliable, volatile (fresh data only)
    reliability=ReliabilityPolicy.RELIABLE,
    durability=DurabilityPolicy.VOLATILE,
    history=HistoryPolicy.KEEP_LAST,
    depth=10,
)
LATCHED_QOS = QoSProfile(  # depth-1 transient-local: late joiners get the last value
    reliability=ReliabilityPolicy.RELIABLE,
    durability=DurabilityPolicy.TRANSIENT_LOCAL,
    history=HistoryPolicy.KEEP_LAST,
    depth=1,
)
