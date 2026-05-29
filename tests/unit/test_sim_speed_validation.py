from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tasks import app
from typer.testing import CliRunner

runner = CliRunner()


def _invoke_stop(*extra):
    """Use 'stop' mode so no subprocess is spawned — we only test arg validation."""
    with patch("tasks.subprocess.run"):
        with patch("tasks._preemptive_world_reset"):
            return runner.invoke(app, ["sim", "stop", *extra])


def test_speed_zero_rejected():
    result = _invoke_stop("--speed", "0")
    assert result.exit_code != 0
    assert "speed" in result.output.lower() or "speed" in str(result.exception).lower()


def test_speed_negative_rejected():
    result = _invoke_stop("--speed", "-1")
    assert result.exit_code != 0


def test_speed_too_high_rejected():
    result = _invoke_stop("--speed", "21")
    assert result.exit_code != 0


def test_speed_one_accepted():
    result = _invoke_stop("--speed", "1.0")
    assert result.exit_code == 0


def test_speed_four_accepted():
    result = _invoke_stop("--speed", "4")
    assert result.exit_code == 0
