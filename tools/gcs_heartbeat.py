#!/usr/bin/env python3
"""Send MAVLink GCS heartbeats and SITL-friendly param overrides for PX4.

PX4 SITL GCS link listens on UDP 18570. The -x flag means it auto-discovers
clients, but it only REPLIES after seeing a valid MAVLink heartbeat from us.
Strategy: send heartbeats immediately in a loop, and once PX4 replies, grab
the system/component ID and send the param overrides.
"""

from __future__ import annotations

import struct
import sys
import time
from pathlib import Path

from pymavlink import mavutil

_PARAMS_FLAG = Path("/tmp/gcs_params_flag")

_PARAMS: tuple[tuple[str, float, str], ...] = (
    ("COM_ARM_WO_GPS", 1.0, "INT32"),  # arm without GPS/EKF fix
    ("CBRK_SUPPLY_CHK", 894281.0, "INT32"),  # bypass battery supply check in SITL
    # In SITL there are no real motors, so the simulated spool-up ramp
    # (default 1 s) just adds dead time between arm and first movement.
    ("COM_SPOOLUP_TIME", 0.0, "REAL32"),  # motor spool-up ramp: 1.0 → 0.0 s (SITL only)
    (
        "EKF2_GPS_CHECK",
        0.0,
        "INT32",
    ),  # bypass GPS quality checks for instant EKF2 GPS fusion in SITL
)

_CONNECT_TIMEOUT_S = 120.0


def _send_params(conn: mavutil.mavudp) -> None:
    for name, value, type_str in _PARAMS:
        if type_str == "INT32":
            type_id = mavutil.mavlink.MAV_PARAM_TYPE_INT32
            vstr = struct.pack(">i", int(value))
            (numeric_value,) = struct.unpack(">f", vstr)
        else:
            type_id = mavutil.mavlink.MAV_PARAM_TYPE_REAL32
            numeric_value = float(value)

        conn.mav.param_set_send(
            conn.target_system,
            conn.target_component,
            name.encode("utf-8"),
            numeric_value,
            type_id,  # type: ignore[unresolved-attribute]
        )


def main() -> None:
    print("[gcs_heartbeat] Connecting to PX4 SITL on UDP 18570...", flush=True)
    conn = mavutil.mavlink_connection("udpout:127.0.0.1:18570")

    # Send our GCS heartbeat immediately so PX4 sees us and starts replying.
    # Then poll for PX4's reply with a short timeout loop.
    deadline = time.monotonic() + _CONNECT_TIMEOUT_S
    got_heartbeat = False
    while time.monotonic() < deadline:
        conn.mav.heartbeat_send(
            mavutil.mavlink.MAV_TYPE_GCS,  # type: ignore[unresolved-attribute]
            mavutil.mavlink.MAV_AUTOPILOT_INVALID,  # type: ignore[unresolved-attribute]
            0,
            0,
            0,
        )
        msg = conn.recv_match(type="HEARTBEAT", blocking=True, timeout=0.1)
        if msg is not None:
            conn.target_system = msg.get_srcSystem()
            conn.target_component = msg.get_srcComponent()
            got_heartbeat = True
            break

    if not got_heartbeat:
        print("[gcs_heartbeat] ERROR: no heartbeat from PX4 within 120s", flush=True)
        sys.exit(1)

    print(
        f"[gcs_heartbeat] Heartbeat from system={conn.target_system} "
        f"component={conn.target_component}. Sending params...",
        flush=True,
    )

    # Retry param_set a few times — UDP is lossy.
    for _ in range(5):
        _send_params(conn)
        time.sleep(0.3)

    _PARAMS_FLAG.write_text(str(time.time()))
    print("[gcs_heartbeat] Params committed. Sending heartbeats...", flush=True)
    last_heartbeat_time = time.monotonic()
    need_send_params = False

    while True:
        conn.mav.heartbeat_send(
            mavutil.mavlink.MAV_TYPE_GCS,  # type: ignore[unresolved-attribute]
            mavutil.mavlink.MAV_AUTOPILOT_INVALID,  # type: ignore[unresolved-attribute]
            0,
            0,
            0,
        )

        # Drain all pending MAVLink messages to avoid socket buffer congestion
        while True:
            msg = conn.recv_match(blocking=False)
            if msg is None:
                break

            if msg.get_type() == "HEARTBEAT":
                now = time.monotonic()
                if now - last_heartbeat_time > 3.0:
                    print(
                        f"[gcs_heartbeat] Connection re-established with system={msg.get_srcSystem()} "
                        f"component={msg.get_srcComponent()}. Re-sending params...",
                        flush=True,
                    )
                    need_send_params = True
                conn.target_system = msg.get_srcSystem()
                conn.target_component = msg.get_srcComponent()
                last_heartbeat_time = now

        if time.monotonic() - last_heartbeat_time > 3.0:
            need_send_params = True

        if need_send_params and time.monotonic() - last_heartbeat_time < 1.0:
            print("[gcs_heartbeat] Re-sending parameters to restarted PX4 SITL...", flush=True)
            for _ in range(3):
                _send_params(conn)
                time.sleep(0.1)
            _PARAMS_FLAG.write_text(str(time.time()))
            print("[gcs_heartbeat] Params committed.", flush=True)
            need_send_params = False

        time.sleep(0.1)


if __name__ == "__main__":
    main()
