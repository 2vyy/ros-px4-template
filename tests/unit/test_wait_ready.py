from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

from typer.testing import CliRunner

from wait_ready import app


def test_ready_requires_standby_gate():
    """Stack ready must wait for all three gates including PX4 STANDBY."""
    runner = CliRunner()
    with (
        patch("wait_ready._topic_live", return_value=True),
        patch("wait_ready._port_open", return_value=True),
        patch("wait_ready._px4_standby", return_value=True),
    ):
        result = runner.invoke(app, ["--timeout", "5"])
    assert result.exit_code == 0
    assert "PX4 in STANDBY" in result.output
    assert "Stack ready" in result.output


def test_ready_blocks_until_standby():
    """Stack ready must not exit while PX4 STANDBY gate is pending."""
    runner = CliRunner()
    call_count = 0

    def fake_standby() -> bool:
        nonlocal call_count
        call_count += 1
        return call_count >= 3  # fails first two polls

    with (
        patch("wait_ready._topic_live", return_value=True),
        patch("wait_ready._port_open", return_value=True),
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
        patch("wait_ready._port_open", return_value=True),
        patch("wait_ready._px4_standby", return_value=False),
    ):
        result = runner.invoke(app, ["--timeout", "1"])
    assert result.exit_code == 1
    assert "params=False" in result.output


# ── _px4_standby unit tests ──────────────────────────────────────────────────


def test_px4_standby_true_when_arming_state_2_in_output():
    mock_result = MagicMock()
    mock_result.stdout = "arming_state: 2\n"
    with patch("subprocess.run", return_value=mock_result):
        from wait_ready import _px4_standby

        assert _px4_standby() is True


def test_px4_standby_false_when_arming_state_not_standby():
    mock_result = MagicMock()
    mock_result.stdout = "arming_state: 1\n"
    with patch("subprocess.run", return_value=mock_result):
        from wait_ready import _px4_standby

        assert _px4_standby() is False


def test_px4_standby_false_on_timeout():
    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="ros2", timeout=3)):
        from wait_ready import _px4_standby

        assert _px4_standby() is False


def test_px4_standby_false_when_ros2_not_found():
    with patch("subprocess.run", side_effect=FileNotFoundError()):
        from wait_ready import _px4_standby

        assert _px4_standby() is False
