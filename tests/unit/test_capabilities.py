"""Unit tests for capabilities registry utilities."""

from __future__ import annotations

from pathlib import Path

import tomli_w

from capabilities import scenarios_for_platform


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


def _load_from(path: Path) -> dict:
    try:
        import tomllib
    except ModuleNotFoundError:
        import tomli as tomllib  # type: ignore[no-redef]
    return tomllib.loads(path.read_text(encoding="utf-8"))
