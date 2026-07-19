from __future__ import annotations

import json
import types
from pathlib import Path

import tasks
from tasks import _e2e_initial_state, _fallback_scenario_report


def test_e2e_initial_state_isolates_scenarios_with_same_config() -> None:
    configs = [
        {
            "scenario": "01_arm_takeoff",
            "vision": "none",
            "overlay": "hover",
            "model": "x500",
            "world": "default",
        },
        {
            "scenario": "02_hover_hold",
            "vision": "none",
            "overlay": "hover",
            "model": "x500",
            "world": "default",
        },
    ]

    groups = _e2e_initial_state(configs)["groups"]
    assert [
        (g["vision"], g["overlay"], g["model"], g["world"], g["scenarios"]) for g in groups
    ] == [
        ("none", "hover", "x500", "default", ["01_arm_takeoff"]),
        ("none", "hover", "x500", "default", ["02_hover_hold"]),
    ]
    for g in groups:
        assert g["state"] == "pending"
        assert g["fails"] == 0


def test_e2e_initial_state_keys() -> None:
    state = _e2e_initial_state(
        [
            {
                "scenario": "01_arm_takeoff",
                "vision": "none",
                "overlay": "hover",
                "model": "x500",
                "world": "default",
            }
        ]
    )
    assert set(state) == {"status", "started_at", "finished_at", "groups"}
    assert state["status"] == "running"
    assert state["finished_at"] is None
    assert set(state["groups"][0]) == {
        "vision",
        "overlay",
        "model",
        "world",
        "scenarios",
        "state",
        "fails",
    }


def test_fallback_report_matches_write_report_shape() -> None:
    data = json.loads(
        _fallback_scenario_report(
            "01_arm_takeoff",
            "crashed_before_report",
            {
                "vision": "none",
                "overlay": "auto_arm",
                "model": "x500",
                "world": "default",
            },
        )
    )

    assert set(data) == {"scenario", "passed", "elapsed_s", "detail"}
    assert data["passed"] is False
    assert data["detail"]["reason"] == "crashed_before_report"
    assert data["detail"]["vision"] == "none"
    assert data["detail"]["overlay"] == "auto_arm"
    assert data["detail"]["model"] == "x500"
    assert data["detail"]["world"] == "default"


def test_blocked_by_transitive_failed_claim() -> None:
    from tasks import _blocked_by

    data = {
        "capabilities": {
            "arm_takeoff": {"scenario_file": "01_arm_takeoff.py", "requires": []},
            "aruco_hover": {
                "scenario_file": "05_aruco_hover.py",
                "requires": ["arm_takeoff"],
            },
            "precision_land": {
                "scenario_file": "08_precision_land.py",
                "requires": ["aruco_hover"],
            },
        }
    }
    assert _blocked_by(data, "08_precision_land", {"arm_takeoff"}) == "arm_takeoff"
    assert _blocked_by(data, "08_precision_land", set()) is None
    assert _blocked_by(data, "01_arm_takeoff", {"aruco_hover"}) is None


def test_fallback_report_is_valid_for_scenario_status() -> None:
    text = _fallback_scenario_report(
        "01_arm_takeoff",
        "no_report_written",
        {"vision": "none", "overlay": "auto_arm", "model": "x500", "world": "default"},
    )

    assert text.endswith("\n")
    assert json.loads(text)["scenario"] == "01_arm_takeoff"


# ── _run_e2e_sim_group: the consolidated record_failure() seam ────────────────


def _patch_group_deps(monkeypatch, log_dir: Path) -> None:
    """Isolate _run_e2e_sim_group from the real stack: no subprocess, no
    readiness polling, no real teardown, and run records land in tmp_path
    instead of the repo's logs/ dir."""
    monkeypatch.setattr(tasks, "LOG_DIR", log_dir)
    monkeypatch.setattr(tasks, "_spawn_stack", lambda *a, **kw: types.SimpleNamespace(pid=4242))
    monkeypatch.setattr(tasks.wait_ready, "wait", lambda timeout: True)
    monkeypatch.setattr(tasks, "_teardown", lambda: True)
    monkeypatch.setattr(tasks.run_supervisor, "RUNS_DIR", log_dir / "runs")
    monkeypatch.setattr(tasks.run_supervisor, "HEARTBEAT", log_dir / "heartbeat")


_REGISTRY = {
    "capabilities": {"arm_takeoff": {"scenario_file": "01_arm_takeoff.py", "requires": []}}
}


def test_stuck_marks_claim_and_leaves_fresh_report_untouched(tmp_path, monkeypatch) -> None:
    _patch_group_deps(monkeypatch, tmp_path)
    report_path = tmp_path / "scenario_01_arm_takeoff.json"
    fresh_report = {
        "scenario": "01_arm_takeoff",
        "passed": False,
        "elapsed_s": 1.0,
        "detail": {"reason": "real_failure_detail"},
    }

    def fake_supervise(argv, name, **kwargs):
        # Simulate the scenario process writing its own report before the
        # supervisor kills it as stuck (e.g. wedged during cleanup).
        report_path.write_text(json.dumps(fresh_report), encoding="utf-8")
        return None, "log_silent"

    monkeypatch.setattr(tasks.run_supervisor, "supervise", fake_supervise)

    failed_claims: set[str] = set()
    fails = tasks._run_e2e_sim_group(
        "none",
        "hover",
        ["01_arm_takeoff"],
        gz_resource="x",
        registry=_REGISTRY,
        failed_claims=failed_claims,
    )

    assert fails == 1
    assert failed_claims == {"arm_takeoff"}
    # A fresh, real report is never clobbered by the synthesized fallback.
    assert json.loads(report_path.read_text(encoding="utf-8")) == fresh_report


def test_crash_without_report_synthesizes_crashed_before_report(tmp_path, monkeypatch) -> None:
    _patch_group_deps(monkeypatch, tmp_path)
    report_path = tmp_path / "scenario_01_arm_takeoff.json"

    def fake_supervise(argv, name, **kwargs):
        return 1, None  # exited nonzero, wrote nothing

    monkeypatch.setattr(tasks.run_supervisor, "supervise", fake_supervise)

    failed_claims: set[str] = set()
    fails = tasks._run_e2e_sim_group(
        "none",
        "hover",
        ["01_arm_takeoff"],
        gz_resource="x",
        registry=_REGISTRY,
        failed_claims=failed_claims,
    )

    assert fails == 1
    assert failed_claims == {"arm_takeoff"}
    data = json.loads(report_path.read_text(encoding="utf-8"))
    assert data["passed"] is False
    assert data["detail"]["reason"] == "crashed_before_report"
