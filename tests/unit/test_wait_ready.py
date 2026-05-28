from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

from typer.testing import CliRunner

from wait_ready import app


def test_ready_requires_params_gate():
    """Stack ready must wait for all three gates including params."""
    runner = CliRunner()
    with (
        patch("wait_ready._topic_live", return_value=True),
        patch("wait_ready._port_open", return_value=True),
        patch("wait_ready._params_sent", return_value=True),
    ):
        result = runner.invoke(app, ["--timeout", "5"])
    assert result.exit_code == 0
    assert "gcs params committed" in result.output
    assert "Stack ready" in result.output


def test_ready_blocks_until_params():
    """Stack ready must not exit while params gate is pending."""
    runner = CliRunner()
    call_count = 0

    def fake_params() -> bool:
        nonlocal call_count
        call_count += 1
        return call_count >= 3  # fails first two polls

    with (
        patch("wait_ready._topic_live", return_value=True),
        patch("wait_ready._port_open", return_value=True),
        patch("wait_ready._params_sent", fake_params),
    ):
        result = runner.invoke(app, ["--timeout", "5"])

    assert result.exit_code == 0
    assert 2 <= call_count < 20  # polled until 3rd call returned True, not indefinitely


def test_timeout_reports_params_state():
    """On timeout, output must include params status."""
    runner = CliRunner()
    with (
        patch("wait_ready._topic_live", return_value=True),
        patch("wait_ready._port_open", return_value=True),
        patch("wait_ready._params_sent", return_value=False),
    ):
        result = runner.invoke(app, ["--timeout", "1"])
    assert result.exit_code == 1
    assert "params=False" in result.output
