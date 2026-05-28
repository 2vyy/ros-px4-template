from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

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


def test_px4_standby_true_when_flag_exists(tmp_path, monkeypatch):
    flag = tmp_path / "gcs_params_flag"
    flag.write_text("12345.6")
    import bench_relaunch

    monkeypatch.setattr(bench_relaunch, "_GCS_PARAMS_FLAG", flag)
    assert bench_relaunch._px4_standby() is True


def test_px4_standby_false_when_flag_missing(tmp_path, monkeypatch):
    flag = tmp_path / "gcs_params_flag"
    import bench_relaunch

    monkeypatch.setattr(bench_relaunch, "_GCS_PARAMS_FLAG", flag)
    assert bench_relaunch._px4_standby() is False
