"""Unit tests for reusable scenario assertion helpers."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tests" / "scenarios"))

from _common import HeldThroughout


def test_held_throughout_reports_no_violations() -> None:
    now = [0.0]
    invariant = HeldThroughout("altitude_limit", lambda: True, clock=lambda: now[0])

    invariant.sample()
    now[0] = 5.0
    invariant.sample()

    assert invariant.held is True
    assert invariant.detail() == {
        "altitude_limit_held": True,
        "altitude_limit_violations": 0,
        "altitude_limit_first_violation_s": None,
    }


def test_held_throughout_records_first_violation_time() -> None:
    now = [0.0]
    ok = [True]
    invariant = HeldThroughout("keep_out", lambda: ok[0], clock=lambda: now[0])

    now[0] = 3.0
    ok[0] = False
    invariant.sample()

    assert invariant.held is False
    assert invariant.violations == 1
    assert invariant.first_violation_t == 3.0
    assert invariant.detail() == {
        "keep_out_held": False,
        "keep_out_violations": 1,
        "keep_out_first_violation_s": 3.0,
    }
