"""Frame transformation utilities for ROS 2 / PX4 projects.

All project code works in ENU (East-North-Up) / REP-103.
These utilities convert at the PX4 boundary (NED ↔ ENU).

Reference:
    ROS REP-103: https://www.ros.org/reps/rep-0103.html
    PX4 frames: https://docs.px4.io/main/en/ros/ros2_comm.html
"""


def ned_to_enu(x_ned: float, y_ned: float, z_ned: float) -> tuple[float, float, float]:
    """Convert NED position to ENU position.

    Args:
        x_ned: North component (meters).
        y_ned: East component (meters).
        z_ned: Down component (meters, positive downward).

    Returns:
        Tuple of (x_enu, y_enu, z_enu) in meters.

    Example:
        >>> ned_to_enu(1.0, 2.0, -3.0)
        (2.0, 1.0, 3.0)
    """
    return y_ned, x_ned, -z_ned


def enu_to_ned(x_enu: float, y_enu: float, z_enu: float) -> tuple[float, float, float]:
    """Convert ENU position to NED for PX4 trajectory setpoints.

    Args:
        x_enu: East component (meters).
        y_enu: North component (meters).
        z_enu: Up component (meters, positive upward).

    Returns:
        Tuple of (x_ned, y_ned, z_ned) in meters.

    Example:
        >>> enu_to_ned(2.0, 1.0, 3.0)
        (1.0, 2.0, -3.0)
    """
    return y_enu, x_enu, -z_enu
