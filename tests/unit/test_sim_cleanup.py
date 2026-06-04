from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

import sim_cleanup


def test_gazebo_killed_on_stop():
    """Cold-start-always policy: Gazebo is torn down on every stop (no warm reuse)."""
    for pat in ("gz sim", "gz server", "gzserver"):
        assert pat in sim_cleanup._PATTERNS, (
            f"{pat!r} must be in _PATTERNS — Gazebo is killed on stop, never kept warm"
        )
    assert "gz" in sim_cleanup._EXACT_NAMES
    assert "gzserver" in sim_cleanup._EXACT_NAMES


def test_px4_killed_on_stop():
    """PX4 SITL is always torn down (no warm reuse across runs)."""
    assert r"/bin/px4$" in sim_cleanup._PATTERNS
    assert "px4" in sim_cleanup._EXACT_NAMES


def test_xrce_agent_killed_on_stop():
    """MicroXRCEAgent is stopped on every sim stop (session key rotates each launch)."""
    assert r"MicroXRCEAgent" in sim_cleanup._PATTERNS
    assert "MicroXRCEAgent" in sim_cleanup._EXACT_NAMES


def test_find_pids_excludes_ancestors():
    """_find_pids must never return ancestor pids (so cleanup can't kill itself)."""
    mock_run = MagicMock(return_value=MagicMock(stdout="1234\n5678\n"))
    with patch("sim_cleanup.subprocess.run", mock_run):
        pids = sim_cleanup._find_pids("anything", ancestor_pids={5678})
    assert pids == [1234]


def test_find_pids_silent_on_exception():
    """_find_pids must not propagate exceptions (best-effort teardown)."""
    with patch("sim_cleanup.subprocess.run", side_effect=Exception("fail")):
        assert sim_cleanup._find_pids("x", ancestor_pids=set()) == []
