"""Pure optional-yaw quaternion codec for ``/drone/target_pose``.

``mission_manager`` publishes ``GoTo.yaw`` (ENU radians, optionally ``None``)
as a ``geometry_msgs/PoseStamped`` orientation quaternion. Since the identity
quaternion is a real ENU yaw of zero, "yaw omitted" needs its own sentinel:
the all-zero quaternion, which is never a valid orientation. This module is
the single place that knows about the sentinel and its malformed-input
handling, so node code never duplicates norm thresholds.

No ROS imports: this is a pure codec, unit-testable without rclpy/geometry_msgs.
"""

from __future__ import annotations

import math

from ros_px4_template_core.lib.frames import enu_quaternion_from_yaw, enu_yaw_from_quaternion

# A quaternion norm within this band of 1.0 is treated as "a real orientation,
# just numerically imperfect" and normalized before extracting yaw. Anything
# further away (but non-zero) is malformed input, not a valid sentinel.
_NEAR_UNIT_TOL = 0.1


def target_yaw_to_quaternion(yaw_enu: float | None) -> tuple[float, float, float, float]:
    """Encode an optional ENU yaw (radians) as a target-pose quaternion.

    ``None`` (yaw omitted) becomes the all-zero sentinel; otherwise delegates
    to :func:`enu_quaternion_from_yaw`.
    """
    if yaw_enu is None:
        return (0.0, 0.0, 0.0, 0.0)
    return enu_quaternion_from_yaw(yaw_enu)


def target_yaw_from_quaternion(q_w: float, q_x: float, q_y: float, q_z: float) -> float | None:
    """Decode a target-pose quaternion back to an optional ENU yaw (radians).

    Returns ``None`` for the all-zero sentinel, for non-finite components, or
    for a quaternion whose norm falls outside the near-unit range (malformed
    input) -- never raises. A near-unit quaternion is normalized before yaw
    extraction so small numerical drift does not bias the result.
    """
    components = (q_w, q_x, q_y, q_z)
    if not all(math.isfinite(c) for c in components):
        return None
    norm = math.sqrt(sum(c * c for c in components))
    if norm == 0.0:
        return None
    if abs(norm - 1.0) > _NEAR_UNIT_TOL:
        return None
    w, x, y, z = (c / norm for c in components)
    return enu_yaw_from_quaternion(w, x, y, z)
