from __future__ import annotations

import sys
from pathlib import Path

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
