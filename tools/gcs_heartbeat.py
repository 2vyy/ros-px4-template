#!/usr/bin/env python3
"""Send MAVLink GCS heartbeats and SITL-friendly param overrides for PX4."""

from __future__ import annotations

import time

from pymavlink import mavutil

_CBRK_SUPPLY_CHK = 894281

_PARAMS: tuple[tuple[str, float], ...] = (
    ("COM_ARM_WO_GPS", 1.0),
    ("CBRK_SUPPLY_CHK", float(_CBRK_SUPPLY_CHK)),
)


def main() -> None:
    # PX4 SITL mavlink instance listens on 18570 (remote target for GCS traffic).
    conn = mavutil.mavlink_connection("udpout:127.0.0.1:18570")
    conn.wait_heartbeat(timeout=120)
    for name, value in _PARAMS:
        conn.mav.param_set_send(
            conn.target_system,
            conn.target_component,
            name.encode("utf-8"),
            value,
            mavutil.mavlink.MAV_PARAM_TYPE_REAL32,
        )
        time.sleep(0.2)
    while True:
        conn.mav.heartbeat_send(
            mavutil.mavlink.MAV_TYPE_GCS,
            mavutil.mavlink.MAV_AUTOPILOT_INVALID,
            0,
            0,
            0,
        )
        time.sleep(1.0)


if __name__ == "__main__":
    main()
