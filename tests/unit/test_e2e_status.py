"""Unit tests for the e2e progress/status builder."""

from __future__ import annotations

import json
import time
from pathlib import Path

from e2e_status import build_status


def _write_state(d: Path, **overrides) -> None:
    state = {
        "status": "running",
        "started_at": time.time() - 120,
        "finished_at": None,
        "speed": 1.0,
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
    text, code = build_status(tmp_path, pid_alive=None)
    assert code == 2
    assert "no e2e run found" in text.lower()


def test_running_exits_3_and_shows_progress(tmp_path: Path) -> None:
    _write_state(tmp_path)
    _write_scenario(tmp_path, "01_arm_takeoff", True)
    (tmp_path / "latest.log").write_text("x", encoding="utf-8")
    text, code = build_status(tmp_path, pid_alive=True)
    assert code == 3
    assert "RUNNING" in text
    assert "group 2/3" in text
    assert "05_aruco_hover" in text
    assert "PASS 01_arm_takeoff" in text
    assert "last activity" in text


def test_running_at_speed_names_the_factor(tmp_path: Path) -> None:
    _write_state(tmp_path, speed=2.0)
    text, code = build_status(tmp_path, pid_alive=True)
    assert code == 3
    assert "at 2.0x" in text


def test_finished_all_pass_exits_0(tmp_path: Path) -> None:
    _write_state(tmp_path, status="passed", finished_at=time.time())
    _write_scenario(tmp_path, "01_arm_takeoff", True)
    text, code = build_status(tmp_path, pid_alive=False)
    assert code == 0
    assert "PASS" in text


def test_finished_with_failures_exits_1(tmp_path: Path) -> None:
    _write_state(tmp_path, status="failed", finished_at=time.time())
    _write_scenario(tmp_path, "01_arm_takeoff", False)
    text, code = build_status(tmp_path, pid_alive=False)
    assert code == 1
    assert "FAIL" in text


def test_dead_supervisor_while_running_is_aborted_exit_1(tmp_path: Path) -> None:
    _write_state(tmp_path)
    text, code = build_status(tmp_path, pid_alive=False)
    assert code == 1
    assert "aborted" in text.lower()


def test_stopped_run_reports_aborted_exit_1(tmp_path: Path) -> None:
    _write_state(tmp_path, status="aborted", finished_at=time.time())
    text, code = build_status(tmp_path, pid_alive=None)
    assert code == 1
    assert "aborted" in text.lower()
