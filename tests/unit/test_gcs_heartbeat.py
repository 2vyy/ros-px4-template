from __future__ import annotations

import struct
from pathlib import Path
from unittest.mock import MagicMock

import gcs_heartbeat


def test_param_table_is_arming_enablers_only() -> None:
    names = {name for name, _, _ in gcs_heartbeat._PARAMS}

    assert names == {"COM_ARM_WO_GPS", "CBRK_SUPPLY_CHK", "COM_SPOOLUP_TIME", "EKF2_GPS_CHECK"}
    assert all(not name.startswith(("SIM_GZ_", "MPC_THR")) for name in names)


def test_param_types_valid() -> None:
    for _name, value, param_type in gcs_heartbeat._PARAMS:
        assert param_type in {"INT32", "REAL32"}
        assert isinstance(value, int | float)
        if param_type == "INT32":
            assert float(value).is_integer()


def test_send_params_packs_int32_as_float_bits() -> None:
    fake = MagicMock()
    fake.target_system = 1
    fake.target_component = 1

    gcs_heartbeat._send_params(fake)

    calls = fake.mav.param_set_send.call_args_list
    sent = {call.args[2].decode("utf-8"): call.args[3] for call in calls}
    for name, value, param_type in gcs_heartbeat._PARAMS:
        if param_type == "INT32":
            packed = struct.pack(">f", sent[name])
            (round_trip,) = struct.unpack(">i", packed)
            assert round_trip == int(value)
        else:
            assert sent[name] == float(value)


def test_send_params_sends_all_params_once() -> None:
    fake = MagicMock()
    fake.target_system = 1
    fake.target_component = 1

    gcs_heartbeat._send_params(fake)

    assert fake.mav.param_set_send.call_count == len(gcs_heartbeat._PARAMS)


def test_flag_path_constant() -> None:
    assert gcs_heartbeat._PARAMS_FLAG == Path("/tmp/gcs_params_flag")
