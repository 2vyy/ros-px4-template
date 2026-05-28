from __future__ import annotations

import sys
import time
from pathlib import Path
from unittest.mock import patch

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


# ── _params_sent ─────────────────────────────────────────────────────────────

def test_params_sent_no_logs(tmp_path):
    from bench_relaunch import _params_sent
    with patch("bench_relaunch.LOG_DIR", tmp_path):
        assert _params_sent(after_mtime=0.0) is False


def test_params_sent_stale_log(tmp_path):
    from bench_relaunch import _params_sent
    log = tmp_path / "sim_20260101T000000.log"
    log.write_text("Params committed\n")
    import os
    old_time = time.time() - 1000
    os.utime(log, (old_time, old_time))
    with patch("bench_relaunch.LOG_DIR", tmp_path):
        # after_mtime is now → log is stale
        assert _params_sent(after_mtime=time.time()) is False


def test_params_sent_fresh_log_with_marker(tmp_path):
    from bench_relaunch import _params_sent
    log = tmp_path / "sim_20260101T000000.log"
    log.write_text("some output\nParams committed\nmore output\n")
    with patch("bench_relaunch.LOG_DIR", tmp_path):
        # after_mtime is in the past → log is fresh
        assert _params_sent(after_mtime=0.0) is True


def test_params_sent_fresh_log_without_marker(tmp_path):
    from bench_relaunch import _params_sent
    log = tmp_path / "sim_20260101T000000.log"
    log.write_text("some output\nno params here\n")
    with patch("bench_relaunch.LOG_DIR", tmp_path):
        assert _params_sent(after_mtime=0.0) is False
