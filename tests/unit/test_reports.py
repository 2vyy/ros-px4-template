"""Unit tests for tools/reports.py (merged e2e_report / e2e_status / scenario_status)."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

from reports import build_block, build_status, format_scenario_status


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


def _write_state(d: Path, **overrides) -> None:
    state = {
        "status": "running",
        "started_at": time.time() - 120,
        "finished_at": None,
        "groups": [
            {
                "vision": "none",
                "overlay": "hover",
                "scenarios": ["01_arm_takeoff"],
                "state": "done",
                "fails": 0,
            },
            {
                "vision": "aruco",
                "overlay": "marker_hover",
                "scenarios": ["05_aruco_hover"],
                "state": "running",
                "fails": 0,
            },
            {
                "vision": "none",
                "overlay": "yaw_demo",
                "scenarios": ["07_yaw_control"],
                "state": "pending",
                "fails": 0,
            },
        ],
    }
    state.update(overrides)
    (d / "e2e_state.json").write_text(json.dumps(state), encoding="utf-8")


def _write_scenario(d: Path, name: str, passed: bool) -> None:
    (d / f"scenario_{name}.json").write_text(
        json.dumps(
            {
                "scenario": name,
                "passed": passed,
                "elapsed_s": 5.0,
                "detail": {} if passed else {"reason": "timeout"},
            }
        ),
        encoding="utf-8",
    )


def test_no_state_file_exits_2(tmp_path: Path) -> None:
    text, code = build_status(tmp_path, worker_alive=None)
    assert code == 2
    assert "no e2e run found" in text.lower()


def test_running_exits_3_and_shows_progress(tmp_path: Path) -> None:
    _write_state(tmp_path)
    _write_scenario(tmp_path, "01_arm_takeoff", True)
    (tmp_path / "latest.log").write_text("x", encoding="utf-8")
    text, code = build_status(tmp_path, worker_alive=True)
    assert code == 3
    assert "RUNNING" in text
    assert "group 2/3" in text
    assert "05_aruco_hover" in text
    assert "PASS 01_arm_takeoff" in text
    assert "last activity" in text


def test_finished_all_pass_exits_0(tmp_path: Path) -> None:
    _write_state(tmp_path, status="passed", finished_at=time.time())
    _write_scenario(tmp_path, "01_arm_takeoff", True)
    text, code = build_status(tmp_path, worker_alive=False)
    assert code == 0
    assert "PASS" in text


def test_finished_with_failures_exits_1(tmp_path: Path) -> None:
    _write_state(tmp_path, status="failed", finished_at=time.time())
    _write_scenario(tmp_path, "01_arm_takeoff", False)
    text, code = build_status(tmp_path, worker_alive=False)
    assert code == 1
    assert "FAIL" in text


def test_dead_supervisor_while_running_is_aborted_exit_1(tmp_path: Path) -> None:
    _write_state(tmp_path)
    text, code = build_status(tmp_path, worker_alive=False)
    assert code == 1
    assert "aborted" in text.lower()


def test_stopped_run_reports_aborted_exit_1(tmp_path: Path) -> None:
    _write_state(tmp_path, status="aborted", finished_at=time.time())
    text, code = build_status(tmp_path, worker_alive=None)
    assert code == 1
    assert "aborted" in text.lower()


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
