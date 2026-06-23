"""Unit tests for the single-scenario verdict helper (no ROS)."""

from __future__ import annotations

import json
import os
from pathlib import Path

from scenario_status import format_scenario_status


def _write(log_dir: Path, name: str, passed: bool, detail: dict, elapsed: float = 1.0) -> Path:
    p = log_dir / f"scenario_{name}.json"
    p.write_text(
        json.dumps({"scenario": name, "passed": passed, "elapsed_s": elapsed, "detail": detail}),
        encoding="utf-8",
    )
    return p


def test_passing_scenario(tmp_path: Path) -> None:
    _write(tmp_path, "x", True, {"alt_m": 2.5})
    line, code = format_scenario_status(tmp_path, "x")
    assert line.startswith("PASS")
    assert "x" in line
    assert code == 0


def test_failing_scenario(tmp_path: Path) -> None:
    _write(tmp_path, "y", False, {"reason": "timeout", "phase": "climb"})
    line, code = format_scenario_status(tmp_path, "y")
    assert line.startswith("FAIL")
    assert "timeout" in line
    assert code == 1


def test_missing_report_is_usage_error(tmp_path: Path) -> None:
    line, code = format_scenario_status(tmp_path, "nope")
    assert code == 2
    assert "no scenario report" in line


def test_empty_dir_default_name(tmp_path: Path) -> None:
    line, code = format_scenario_status(tmp_path, None)
    assert code == 2
    assert "no scenario report" in line


def test_default_picks_most_recent(tmp_path: Path) -> None:
    old = _write(tmp_path, "old", True, {})
    new = _write(tmp_path, "new", False, {"reason": "boom"})
    os.utime(old, (1_000_000, 1_000_000))
    os.utime(new, (2_000_000, 2_000_000))
    line, code = format_scenario_status(tmp_path, None)
    assert "new" in line
    assert code == 1
