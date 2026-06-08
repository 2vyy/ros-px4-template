from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tasks import app
from typer.testing import CliRunner

runner = CliRunner()


def test_speed_zero_rejected():
    result = runner.invoke(app, ["sim", "--speed", "0"])
    assert result.exit_code != 0
    assert "speed" in result.output.lower() or "speed" in str(result.exception).lower()


def test_speed_negative_rejected():
    result = runner.invoke(app, ["sim", "--speed", "-1"])
    assert result.exit_code != 0


def test_speed_too_high_rejected():
    result = runner.invoke(app, ["sim", "--speed", "1.1"])
    assert result.exit_code != 0


def test_speed_one_accepted():
    """Speed 1.0 passes validation; mock everything downstream so the test is unit-only."""
    completed_ok = MagicMock(returncode=0)
    popen_proc = MagicMock()
    popen_proc.pid = 99999
    with (
        patch("tasks.subprocess.run", return_value=completed_ok),
        patch("tasks.subprocess.Popen", return_value=popen_proc),
        patch("tasks._teardown"),
        patch("tasks._smart_build"),
        patch("tasks.LOG_DIR", new=Path("/tmp/tasks_test_log_dir")),
    ):
        Path("/tmp/tasks_test_log_dir").mkdir(parents=True, exist_ok=True)
        # Ensure no stale pid file trips the idempotency guard
        pid_file = Path("/tmp/tasks_test_log_dir/sim.pid")
        if pid_file.exists():
            pid_file.unlink()
        result = runner.invoke(app, ["sim", "--speed", "1.0", "--no-build"])
    assert result.exit_code == 0, f"exit={result.exit_code}, output={result.output}"
