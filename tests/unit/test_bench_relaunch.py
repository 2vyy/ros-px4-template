from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))


# ── _format_milestone ────────────────────────────────────────────────────────


def test_format_milestone_no_launch_ref():
    from bench_relaunch import _format_milestone

    t0 = 1000.0
    line = _format_milestone("sim stop complete", 1003.1, t0)
    assert "+3.1s" in line
    assert "sim stop complete" in line
    assert "from launch" not in line


def test_format_milestone_with_launch_ref():
    from bench_relaunch import _format_milestone

    t0 = 1000.0
    t_launch = 1003.4
    line = _format_milestone("XRCE / first topic live", 1014.2, t0, t_launch)
    assert "+14.2s" in line
    assert "+10.8s from launch" in line


# ── _px4_standby ─────────────────────────────────────────────────────────────


def test_px4_standby_true_when_arming_state_2_in_output():
    mock_result = MagicMock()
    mock_result.stdout = "arming_state: 2\nsome_other_field: 1\n"
    with patch("subprocess.run", return_value=mock_result):
        from bench_relaunch import _px4_standby

        assert _px4_standby() is True


def test_px4_standby_false_when_arming_state_not_2():
    mock_result = MagicMock()
    mock_result.stdout = "arming_state: 1\n"
    with patch("subprocess.run", return_value=mock_result):
        from bench_relaunch import _px4_standby

        assert _px4_standby() is False


def test_px4_standby_false_on_timeout():
    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="ros2", timeout=3)):
        from bench_relaunch import _px4_standby

        assert _px4_standby() is False


def test_px4_standby_false_when_ros2_not_found():
    with patch("subprocess.run", side_effect=FileNotFoundError()):
        from bench_relaunch import _px4_standby

        assert _px4_standby() is False
