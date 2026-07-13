"""Unit tests for capabilities registry utilities."""

from __future__ import annotations

from pathlib import Path

import tomli_w

from capabilities import scenario_sim_configs, scenarios_for_platform


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


def test_scenario_sim_configs_reads_vision_and_overlay(tmp_path: Path) -> None:
    reg = tmp_path / "capabilities.toml"
    _write_registry(
        reg,
        {
            "arm_takeoff": {
                "description": "Arms",
                "scenario_file": "01_arm_takeoff.py",
                "platforms": ["sim"],
                "status": "verified",
                "sim_vision": "none",
                "sim_overlay": "hover",
            },
            "aruco_hover": {
                "description": "Aruco",
                "scenario_file": "05_aruco_hover.py",
                "platforms": ["sim"],
                "status": "idea",
                "sim_vision": "aruco",
                "sim_overlay": "auto_arm",
                "sim_model": "x500_mono_cam_down",
                "sim_world": "marker_field",
            },
        },
    )
    result = scenario_sim_configs("sim", registry=reg)
    assert result == [
        {
            "scenario": "01_arm_takeoff",
            "vision": "none",
            "overlay": "hover",
            "model": "x500",
            "world": "default",
        },
        {
            "scenario": "05_aruco_hover",
            "vision": "aruco",
            "overlay": "auto_arm",
            "model": "x500_mono_cam_down",
            "world": "marker_field",
        },
    ]


def test_scenario_sim_configs_defaults_when_fields_missing(tmp_path: Path) -> None:
    reg = tmp_path / "capabilities.toml"
    _write_registry(
        reg,
        {
            "waypoint_nav": {
                "description": "Waypoints",
                "scenario_file": "03_waypoint.py",
                "platforms": ["sim"],
                "status": "verified",
            },
        },
    )
    result = scenario_sim_configs("sim", registry=reg)
    assert result == [
        {
            "scenario": "03_waypoint",
            "vision": "none",
            "overlay": "auto_arm",
            "model": "x500",
            "world": "default",
        }
    ]


def _load_from(path: Path) -> dict:
    import tomllib

    return tomllib.loads(path.read_text(encoding="utf-8"))
