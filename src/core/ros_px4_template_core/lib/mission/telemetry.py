"""Pure normalization of raw PX4 telemetry into mission-safe values. No ROS imports."""

from __future__ import annotations

import math


def usable_battery_remaining(*, connected: bool, remaining: float) -> float | None:
    """Return a usable battery fraction, or ``None`` when it cannot be trusted.

    ``BatteryStatus.remaining`` uses ``-1`` as its invalid sentinel and is only
    meaningful while ``connected`` is true. Unknown/invalid/out-of-range input
    must not be mistaken for a real low-battery fraction, so this returns
    ``None`` for anything disconnected, non-finite, or outside ``[0, 1]``.
    """
    if not connected:
        return None
    if not math.isfinite(remaining):
        return None
    if remaining < 0.0 or remaining > 1.0:
        return None
    return float(remaining)
