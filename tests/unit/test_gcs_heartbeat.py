from __future__ import annotations

import struct
from pathlib import Path
from typing import Any, cast
from unittest.mock import MagicMock

import gcs_heartbeat


def test_param_table_is_arming_enablers_only() -> None:
    names = {name for name, _, _ in gcs_heartbeat._PARAMS}

    assert names == {
        "COM_ARM_WO_GPS",
        "CBRK_SUPPLY_CHK",
        "COM_SPOOLUP_TIME",
        "EKF2_GPS_CHECK",
        "EKF2_GPS_CTRL",
    }
    assert all(not name.startswith(("SIM_GZ_", "MPC_THR")) for name in names)


def test_param_table_matches_startup_exports() -> None:
    # The boot-time authoritative copy lives in sim/launch/_start_gz_px4.sh as
    # `export PX4_PARAM_<NAME>=`; the runtime re-send copy is _PARAMS. Drift
    # between the two is a latent arming/EKF bug, so pin them equal permanently.
    import re

    script = Path(__file__).resolve().parents[2] / "sim" / "launch" / "_start_gz_px4.sh"
    exported = set(re.findall(r"^export PX4_PARAM_(\w+)=", script.read_text(), re.MULTILINE))
    names = {name for name, _, _ in gcs_heartbeat._PARAMS}
    assert exported == names


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


# ── PARAM_VALUE read-back confirmation (plan 056) ─────────────────────────────


def _encode_param_value(value: float, type_str: str) -> float:
    """Encode a value the way PX4 echoes it in PARAM_VALUE (INT32 as float bits)."""
    if type_str == "INT32":
        (as_float,) = struct.unpack(">f", struct.pack(">i", int(value)))
        return as_float
    return float(value)


class _FakePv:
    def __init__(self, param_id: str, param_value: float) -> None:
        self.param_id = param_id
        self.param_value = param_value


class _FakeConn:
    """Records param requests; echoes queued PARAM_VALUE replies for _confirm_params."""

    def __init__(self, echo: dict[str, float]) -> None:
        self.target_system = 1
        self.target_component = 1
        self._echo = echo
        self._queue: list[_FakePv] = []
        self.mav = MagicMock()
        self.mav.param_request_read_send.side_effect = self._on_request

    def _on_request(self, _sys: int, _comp: int, name: bytes, _idx: int) -> None:
        key = name.decode("utf-8") if isinstance(name, bytes) else name
        if key in self._echo:
            self._queue.append(_FakePv(key, self._echo[key]))

    def recv_match(self, **_kwargs: Any) -> _FakePv | None:
        return self._queue.pop(0) if self._queue else None


def _all_echo() -> dict[str, float]:
    return {n: _encode_param_value(v, t) for n, v, t in gcs_heartbeat._PARAMS}


def test_confirm_params_all_echo() -> None:
    conn = _FakeConn(_all_echo())
    ok, missing = gcs_heartbeat._confirm_params(cast(Any, conn), timeout_s=0.5)
    assert ok is True
    assert missing == []


def test_confirm_params_reports_missing_name() -> None:
    echo = _all_echo()
    del echo["EKF2_GPS_CHECK"]
    conn = _FakeConn(echo)
    ok, missing = gcs_heartbeat._confirm_params(cast(Any, conn), timeout_s=0.5)
    assert ok is False
    assert missing == ["EKF2_GPS_CHECK"]


def test_param_value_matches_int32_union_round_trip() -> None:
    encoded = _encode_param_value(894281, "INT32")  # CBRK_SUPPLY_CHK
    assert gcs_heartbeat._param_value_matches(encoded, 894281, "INT32") is True
    assert gcs_heartbeat._param_value_matches(encoded, 894282, "INT32") is False


def test_param_value_matches_real32_close() -> None:
    assert gcs_heartbeat._param_value_matches(0.0, 0.0, "REAL32") is True
    assert gcs_heartbeat._param_value_matches(1.0, 0.0, "REAL32") is False
