from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

from typer.testing import CliRunner

import wait_ready
from wait_ready import app


def test_ready_requires_standby_gate():
    """Stack ready must wait for all three gates including GCS params committed."""
    runner = CliRunner()
    with (
        patch("wait_ready._topic_live", return_value=True),
        patch("wait_ready._rosbridge_ws_ok", return_value=True),
        patch("wait_ready._px4_standby", return_value=True),
    ):
        result = runner.invoke(app, ["--timeout", "5"])
    assert result.exit_code == 0
    assert "GCS params committed" in result.output
    assert "Stack ready" in result.output


def test_ready_blocks_until_standby():
    """Stack ready must not exit while PX4 STANDBY gate is pending."""
    runner = CliRunner()
    call_count = 0

    def fake_standby(not_before: float) -> bool:
        nonlocal call_count
        call_count += 1
        return call_count >= 3  # fails first two polls

    with (
        patch("wait_ready._topic_live", return_value=True),
        patch("wait_ready._rosbridge_ws_ok", return_value=True),
        patch("wait_ready._px4_standby", fake_standby),
    ):
        result = runner.invoke(app, ["--timeout", "5"])

    assert result.exit_code == 0
    assert 2 <= call_count < 20  # polled until 3rd call returned True, not indefinitely


def test_timeout_reports_standby_state():
    """On timeout, output must include params status."""
    runner = CliRunner()
    with (
        patch("wait_ready._topic_live", return_value=True),
        patch("wait_ready._rosbridge_ws_ok", return_value=True),
        patch("wait_ready._px4_standby", return_value=False),
    ):
        result = runner.invoke(app, ["--timeout", "1"])
    assert result.exit_code == 1
    assert "standby=False" in result.output


def test_set_physics_path_is_gone():
    """Guard against reintroduction: ANY live gz set_physics call latently corrupts
    PX4's altitude estimate (plans/065 spike truth table), so wait_ready must have
    no speed option and no set_physics helper."""
    assert not hasattr(wait_ready, "_set_physics_speed")
    runner = CliRunner()
    result = runner.invoke(app, ["--timeout", "5", "--speed", "0.5"])
    assert result.exit_code != 0


# ── _px4_standby unit tests ──────────────────────────────────────────────────


def test_px4_standby_true_when_flag_fresh(tmp_path, monkeypatch):
    import os

    flag = tmp_path / "gcs_params_flag"
    flag.write_text("12345.6")
    os.utime(flag, (5000.0, 5000.0))
    import wait_ready

    monkeypatch.setattr(wait_ready, "_GCS_PARAMS_FLAG", flag)
    assert wait_ready._px4_standby(4000.0) is True  # mtime 5000 >= start 4000


def test_px4_standby_false_when_flag_stale(tmp_path, monkeypatch):
    # A flag left behind by a previous session (mtime before this waiter started)
    # must NOT satisfy the standby gate.
    import os

    flag = tmp_path / "gcs_params_flag"
    flag.write_text("12345.6")
    os.utime(flag, (1000.0, 1000.0))
    import wait_ready

    monkeypatch.setattr(wait_ready, "_GCS_PARAMS_FLAG", flag)
    assert wait_ready._px4_standby(2000.0) is False  # mtime 1000 < start 2000


def test_px4_standby_false_when_flag_missing(tmp_path, monkeypatch):
    flag = tmp_path / "gcs_params_flag"
    import wait_ready

    monkeypatch.setattr(wait_ready, "_GCS_PARAMS_FLAG", flag)
    assert wait_ready._px4_standby(0.0) is False
