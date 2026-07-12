#!/usr/bin/env python3
"""Send MAVLink GCS heartbeats and SITL-friendly param overrides for PX4.

PX4 SITL GCS link listens on UDP 18570. The -x flag means it auto-discovers
clients, but it only REPLIES after seeing a valid MAVLink heartbeat from us.
Strategy: send heartbeats immediately in a loop, and once PX4 replies, grab
the system/component ID and send the param overrides.
"""

from __future__ import annotations

import math
import struct
import sys
import time
from pathlib import Path
from typing import Any, cast

from pymavlink import mavutil

_PARAMS_FLAG = Path("/tmp/gcs_params_flag")

_PARAMS: tuple[tuple[str, float, str], ...] = (
    # Arming enablers only. Do NOT push SIM_GZ_EC_MIN / MPC_THR_* — stock thrust
    # calibration gives stable offboard hold (verified vs bare PX4 SITL); the old
    # EC_MIN=0 override broke flight and is gone.
    # Keep in lockstep with the PX4_PARAM_* exports in
    # sim/launch/_start_gz_px4.sh (boot-time authoritative copy); the parity test
    # in test_gcs_heartbeat.py fails if the two lists drift.
    ("COM_ARM_WO_GPS", 1, "INT32"),
    ("CBRK_SUPPLY_CHK", 894281, "INT32"),
    ("COM_SPOOLUP_TIME", 0.0, "REAL32"),
    ("EKF2_GPS_CHECK", 0, "INT32"),
    ("EKF2_GPS_CTRL", 7, "INT32"),
)

_CONNECT_TIMEOUT_S = 120.0


def _mavlink() -> Any:
    return cast(Any, mavutil.mavlink)


def _send_params(conn: mavutil.mavudp) -> None:
    mavlink = _mavlink()
    for name, value, type_str in _PARAMS:
        if type_str == "INT32":
            type_id = mavlink.MAV_PARAM_TYPE_INT32
            vstr = struct.pack(">i", int(value))
            (numeric_value,) = struct.unpack(">f", vstr)
        else:
            type_id = mavlink.MAV_PARAM_TYPE_REAL32
            numeric_value = float(value)

        conn.mav.param_set_send(
            conn.target_system,
            conn.target_component,
            name.encode("utf-8"),
            numeric_value,
            type_id,  # type: ignore[unresolved-attribute]
        )


def _param_value_matches(received: float, expected: float, type_str: str) -> bool:
    """True if a PARAM_VALUE float echoes the value we set.

    INT32 params travel as the int's raw bytes reinterpreted as float32 (the same
    union convention _send_params encodes), so decode the received float the same
    way before comparing. REAL32 params compare with a small tolerance.
    """
    if type_str == "INT32":
        (as_int,) = struct.unpack(">i", struct.pack(">f", received))
        return as_int == int(expected)
    return math.isclose(received, float(expected), rel_tol=1e-6, abs_tol=1e-9)


def _confirm_params(conn: mavutil.mavudp, timeout_s: float = 2.0) -> tuple[bool, list[str]]:
    """Request each _PARAMS entry back and check PX4 echoes the value we set.

    Returns ``(all_confirmed, missing_names)``. Never raises: a param that does
    not echo a matching value within its per-param slice of ``timeout_s`` is
    reported missing. ``timeout_s`` is kept short so this cannot starve the GCS
    heartbeat cadence (PX4 drops the link after ~3 s of silence).
    """
    per_param = timeout_s / max(len(_PARAMS), 1)
    missing: list[str] = []
    for name, value, type_str in _PARAMS:
        conn.mav.param_request_read_send(
            conn.target_system, conn.target_component, name.encode("utf-8"), -1
        )
        deadline = time.monotonic() + per_param
        confirmed = False
        while time.monotonic() < deadline:
            msg = conn.recv_match(type="PARAM_VALUE", blocking=True, timeout=0.2)
            if msg is None:
                continue
            pid = msg.param_id
            if isinstance(pid, bytes):
                pid = pid.decode("utf-8", "ignore")
            if pid.rstrip("\x00") != name:
                continue
            if _param_value_matches(msg.param_value, value, type_str):
                confirmed = True
                break
        if not confirmed:
            missing.append(name)
    return (not missing, missing)


def _send_and_confirm(conn: mavutil.mavudp, attempts: int = 3) -> None:
    """Send params, confirm them via PARAM_VALUE read-back, then write the flag.

    Writes _PARAMS_FLAG regardless of confirmation: the boot-time PX4_PARAM_*
    env exports already applied these (see _start_gz_px4.sh), so READY is not
    held hostage to a lossy GCS link. The log now distinguishes confirmed from
    the missing names -- the diagnostic that was absent before.
    """
    ok = False
    missing: list[str] = []
    for _ in range(attempts):
        _send_params(conn)
        ok, missing = _confirm_params(conn)
        if ok:
            break
    if ok:
        print("[gcs_heartbeat] Params confirmed by PX4.", flush=True)
    else:
        print(
            f"[gcs_heartbeat] WARNING: params NOT confirmed: {missing} "
            "(boot-time env exports remain in effect)",
            flush=True,
        )
    _PARAMS_FLAG.write_text(str(time.time()))


def main() -> None:
    print("[gcs_heartbeat] Connecting to PX4 SITL on UDP 18570...", flush=True)
    conn = mavutil.mavlink_connection("udpout:127.0.0.1:18570")
    mavlink = _mavlink()

    # Send our GCS heartbeat immediately so PX4 sees us and starts replying.
    # Then poll for PX4's reply with a short timeout loop.
    deadline = time.monotonic() + _CONNECT_TIMEOUT_S
    got_heartbeat = False
    while time.monotonic() < deadline:
        conn.mav.heartbeat_send(
            mavlink.MAV_TYPE_GCS,
            mavlink.MAV_AUTOPILOT_INVALID,
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

    # Send + confirm via PARAM_VALUE read-back (UDP is lossy), then flag committed.
    _send_and_confirm(conn)
    print("[gcs_heartbeat] Params committed. Sending heartbeats...", flush=True)
    last_heartbeat_time = time.monotonic()
    need_send_params = False

    while True:
        conn.mav.heartbeat_send(
            mavlink.MAV_TYPE_GCS,
            mavlink.MAV_AUTOPILOT_INVALID,
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
            _send_and_confirm(conn)
            print("[gcs_heartbeat] Params committed.", flush=True)
            need_send_params = False

        time.sleep(0.1)


if __name__ == "__main__":
    main()
