"""Unit tests for the e2e aggregate verdict block."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

from e2e_report import build_block


def test_build_block_reads_scenario_files(tmp_path: Path) -> None:
    (tmp_path / "scenario_01_arm_takeoff.json").write_text(
        json.dumps(
            {
                "scenario": "01_arm_takeoff",
                "passed": True,
                "elapsed_s": 6.2,
                "detail": {"alt_m": 2.5},
            }
        )
    )
    (tmp_path / "scenario_03_waypoint.json").write_text(
        json.dumps(
            {
                "scenario": "03_waypoint",
                "passed": False,
                "elapsed_s": 61.0,
                "detail": {"reason": "timeout", "phase": "climb"},
            }
        )
    )
    block, code = build_block(tmp_path)
    assert "PASS 01_arm_takeoff" in block
    assert "alt_m=2.5" in block
    assert "FAIL 03_waypoint" in block
    assert "timeout" in block
    assert "2 scenarios: 1 PASS, 1 FAIL" in block
    assert code == 1


def test_build_block_all_pass_exit_0(tmp_path: Path) -> None:
    (tmp_path / "scenario_01.json").write_text(
        json.dumps({"scenario": "01", "passed": True, "elapsed_s": 1.0, "detail": {}})
    )
    _block, code = build_block(tmp_path)
    assert code == 0


def test_build_block_empty_is_failure(tmp_path: Path) -> None:
    block, code = build_block(tmp_path)
    assert code == 1
    assert "no scenarios" in block.lower()


def test_build_block_lists_never_ready_scenarios(tmp_path: Path) -> None:
    (tmp_path / "scenario_01_arm_takeoff.json").write_text(
        json.dumps(
            {
                "scenario": "01_arm_takeoff",
                "passed": True,
                "elapsed_s": 6.2,
                "detail": {"alt_m": 2.5},
            }
        )
    )
    (tmp_path / "scenario_05_marker_hover.json").write_text(
        json.dumps(
            {
                "scenario": "05_marker_hover",
                "passed": False,
                "elapsed_s": 0.0,
                "detail": {"reason": "sim_never_ready", "vision": "aruco", "overlay": "hover"},
            }
        )
    )
    block, code = build_block(tmp_path)
    assert code == 1
    assert "FAIL 05_marker_hover" in block
    assert "sim_never_ready" in block
