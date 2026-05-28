from __future__ import annotations

import signal
import sys
from pathlib import Path
from unittest.mock import MagicMock, call, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

import sim_cleanup


def test_gz_excluded_from_default_patterns():
    gz_patterns = {"gz sim", "gz server", "gzserver"}
    for pat in gz_patterns:
        assert pat not in sim_cleanup._PATTERNS, (
            f"{pat!r} must NOT be in _PATTERNS (Gazebo stays warm on normal stop)"
        )


def test_gz_included_in_full_patterns():
    gz_patterns = {"gz sim", "gz server", "gzserver"}
    for pat in gz_patterns:
        assert pat in sim_cleanup._FULL_PATTERNS, (
            f"{pat!r} must be in _FULL_PATTERNS (killed on --full)"
        )


def test_full_patterns_is_superset():
    for pat in sim_cleanup._PATTERNS:
        assert pat in sim_cleanup._FULL_PATTERNS, (
            "_FULL_PATTERNS must contain everything in _PATTERNS"
        )


def test_xrce_agent_excluded_from_default_patterns():
    """MicroXRCEAgent must NOT be killed on normal sim stop (kept alive for reuse)."""
    assert r"MicroXRCEAgent" not in sim_cleanup._PATTERNS, (
        "MicroXRCEAgent must not be in _PATTERNS — it is kept alive across warm stops"
    )


def test_xrce_agent_included_in_full_patterns():
    """MicroXRCEAgent must be killed on --full teardown."""
    assert r"MicroXRCEAgent" in sim_cleanup._FULL_PATTERNS, (
        "MicroXRCEAgent must be in _FULL_PATTERNS — killed only on full teardown"
    )


def test_graceful_px4_stop_sends_sigterm():
    """_graceful_px4_stop must SIGTERM the PX4 pid found by pgrep."""
    mock_run = MagicMock()
    mock_run.return_value = MagicMock(stdout="1234\n5678\n")
    with (
        patch("sim_cleanup.subprocess.run", mock_run),
        patch("sim_cleanup.os.kill") as mock_kill,
        patch("sim_cleanup.time.sleep"),
    ):
        from sim_cleanup import _graceful_px4_stop

        _graceful_px4_stop()
    assert call(1234, signal.SIGTERM) in mock_kill.call_args_list
    assert call(5678, signal.SIGTERM) in mock_kill.call_args_list


def test_graceful_px4_stop_silent_on_no_px4():
    """_graceful_px4_stop must not raise if pgrep finds nothing."""
    mock_run = MagicMock()
    mock_run.return_value = MagicMock(stdout="")
    with (
        patch("sim_cleanup.subprocess.run", mock_run),
        patch("sim_cleanup.os.kill") as mock_kill,
        patch("sim_cleanup.time.sleep"),
    ):
        from sim_cleanup import _graceful_px4_stop

        _graceful_px4_stop()
    mock_kill.assert_not_called()


def test_graceful_px4_stop_silent_on_exception():
    """_graceful_px4_stop must not propagate exceptions."""
    with patch("sim_cleanup.subprocess.run", side_effect=Exception("fail")):
        from sim_cleanup import _graceful_px4_stop

        _graceful_px4_stop()  # must not raise
