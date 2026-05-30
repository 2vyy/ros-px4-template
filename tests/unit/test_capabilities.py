"""Unit tests for capabilities registry utilities."""

from __future__ import annotations

from pathlib import Path

import tomli_w

from capabilities import scenarios_for_platform, update_from_scenario


def _write_registry(path: Path, caps: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(tomli_w.dumps({"capabilities": caps}), encoding="utf-8")


def test_scenarios_for_platform_sim(tmp_path: Path) -> None:
    reg = tmp_path / "capabilities.toml"
    _write_registry(
        reg,
        {
            "arm_takeoff": {
                "description": "Arms and takes off",
                "scenario_file": "01_arm_takeoff.py",
                "platforms": ["sim"],
                "status": "verified",
            },
            "hover_hold": {
                "description": "Holds position",
                "scenario_file": "02_hover_hold.py",
                "platforms": ["sim"],
                "status": "verified",
            },
            "inspect_path_aruco": {
                "description": "Inspect with ArUco",
                "scenario_file": "inspect_aruco.py",
                "platforms": [],
                "status": "not_started",
            },
        },
    )
    result = scenarios_for_platform("sim", registry=reg)
    assert result == ["01_arm_takeoff", "02_hover_hold"]


def test_scenarios_for_platform_excludes_no_scenario_file(tmp_path: Path) -> None:
    reg = tmp_path / "capabilities.toml"
    _write_registry(
        reg,
        {
            "arm_takeoff": {
                "description": "Arms",
                "scenario_file": "01_arm_takeoff.py",
                "platforms": ["sim"],
                "status": "verified",
            },
            "manual_check": {
                "description": "Manual",
                "platforms": ["sim"],
                "status": "verified",
            },
        },
    )
    result = scenarios_for_platform("sim", registry=reg)
    assert result == ["01_arm_takeoff"]


def test_scenarios_for_platform_empty_registry(tmp_path: Path) -> None:
    reg = tmp_path / "capabilities.toml"
    assert scenarios_for_platform("sim", registry=reg) == []


def _load_from(path: Path) -> dict:
    try:
        import tomllib
    except ModuleNotFoundError:
        import tomli as tomllib  # type: ignore[no-redef]
    return tomllib.loads(path.read_text(encoding="utf-8"))


def test_update_from_scenario_pass_increments_counts(tmp_path: Path) -> None:
    reg = tmp_path / "capabilities.toml"
    _write_registry(
        reg,
        {
            "arm_takeoff": {
                "description": "Arms and takes off",
                "scenario_file": "01_arm_takeoff.py",
                "platforms": ["sim"],
                "status": "verified",
            },
        },
    )
    found = update_from_scenario("01_arm_takeoff", "sim", passed=True, registry=reg)
    assert found is True
    data = _load_from(reg)
    cap = data["capabilities"]["arm_takeoff"]
    assert cap["run_count"] == 1
    assert cap["pass_count"] == 1
    assert cap["status"] == "verified"
    assert "last_verified" in cap


def test_update_from_scenario_fail_increments_run_count_only(tmp_path: Path) -> None:
    reg = tmp_path / "capabilities.toml"
    _write_registry(
        reg,
        {
            "arm_takeoff": {
                "description": "Arms and takes off",
                "scenario_file": "01_arm_takeoff.py",
                "platforms": ["sim"],
                "status": "verified",
                "run_count": 5,
                "pass_count": 5,
            },
        },
    )
    found = update_from_scenario("01_arm_takeoff", "sim", passed=False, registry=reg)
    assert found is True
    data = _load_from(reg)
    cap = data["capabilities"]["arm_takeoff"]
    assert cap["run_count"] == 6
    assert cap["pass_count"] == 5


def test_update_from_scenario_no_match_returns_false(tmp_path: Path) -> None:
    reg = tmp_path / "capabilities.toml"
    _write_registry(
        reg,
        {
            "arm_takeoff": {
                "description": "Arms",
                "scenario_file": "01_arm_takeoff.py",
                "platforms": ["sim"],
                "status": "verified",
            },
        },
    )
    found = update_from_scenario("99_unknown", "sim", passed=True, registry=reg)
    assert found is False


def test_update_from_scenario_accumulates_across_calls(tmp_path: Path) -> None:
    reg = tmp_path / "capabilities.toml"
    _write_registry(
        reg,
        {
            "hover_hold": {
                "description": "Hover",
                "scenario_file": "02_hover_hold.py",
                "platforms": ["sim"],
                "status": "verified",
            },
        },
    )
    update_from_scenario("02_hover_hold", "sim", passed=True, registry=reg)
    update_from_scenario("02_hover_hold", "sim", passed=False, registry=reg)
    update_from_scenario("02_hover_hold", "sim", passed=True, registry=reg)
    data = _load_from(reg)
    cap = data["capabilities"]["hover_hold"]
    assert cap["run_count"] == 3
    assert cap["pass_count"] == 2
