"""Unit tests for capabilities registry utilities."""

from __future__ import annotations

from pathlib import Path

import tomli_w

from capabilities import scenario_sim_configs


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
            },
            "hover_hold": {
                "description": "Holds position",
                "scenario_file": "02_hover_hold.py",
                "platforms": ["sim"],
            },
        },
    )
    result = [c["scenario"] for c in scenario_sim_configs("sim", registry=reg)]
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
            },
            "manual_check": {
                "description": "Manual",
                "platforms": ["sim"],
            },
        },
    )
    result = [c["scenario"] for c in scenario_sim_configs("sim", registry=reg)]
    assert result == ["01_arm_takeoff"]


def test_scenarios_for_platform_empty_registry(tmp_path: Path) -> None:
    reg = tmp_path / "capabilities.toml"
    assert [c["scenario"] for c in scenario_sim_configs("sim", registry=reg)] == []


def test_scenario_sim_configs_reads_vision_and_overlay(tmp_path: Path) -> None:
    reg = tmp_path / "capabilities.toml"
    _write_registry(
        reg,
        {
            "arm_takeoff": {
                "description": "Arms",
                "scenario_file": "01_arm_takeoff.py",
                "platforms": ["sim"],
                "sim_vision": "none",
                "sim_overlay": "hover",
            },
            "aruco_hover": {
                "description": "Aruco",
                "scenario_file": "05_aruco_hover.py",
                "platforms": ["sim"],
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


def test_e2e_roster_topo_orders_and_excludes_unscaffolded(tmp_path: Path) -> None:
    from capabilities import e2e_roster

    reg = tmp_path / "capabilities.toml"
    _write_registry(
        reg,
        {
            # registry order deliberately NOT topo order
            "precision_land": {
                "description": "d",
                "platforms": ["sim"],
                "scenario_file": "08_precision_land.py",
                "requires": ["aruco_hover"],
            },
            "aruco_hover": {
                "description": "d",
                "platforms": ["sim"],
                "scenario_file": "05_aruco_hover.py",
                "requires": [],
            },
            "rover_follow": {
                "description": "d",
                "platforms": ["sim"],
                "scenario_file": "10_rover_follow.py",
                "requires": ["aruco_hover"],
            },
            "challenge": {"description": "d", "requires": ["rover_follow"]},
        },
    )

    def artifacts_ok(entry: dict) -> tuple[bool, str]:
        ok = entry.get("scenario_file") != "10_rover_follow.py"
        return ok, "" if ok else "scenario missing"

    configs, excluded = e2e_roster(_load_from(reg), artifacts_ok)
    assert [c["scenario"] for c in configs] == ["05_aruco_hover", "08_precision_land"]
    assert excluded == ["rover_follow"]


def test_claim_for_scenario_maps_stem() -> None:
    from capabilities import claim_for_scenario

    data = {"capabilities": {"aruco_hover": {"scenario_file": "05_aruco_hover.py"}}}
    assert claim_for_scenario(data, "05_aruco_hover") == "aruco_hover"
    assert claim_for_scenario(data, "zz_missing") is None


def test_e2e_roster_and_sim_configs_share_one_config_shape(tmp_path: Path) -> None:
    """The two roster builders must emit the identical dict for the same entry."""
    reg = tmp_path / "capabilities.toml"
    _write_registry(
        reg,
        {
            "aruco_hover_real": {
                "description": "Real-pixel hover",
                "scenario_file": "09_aruco_hover_real.py",
                "platforms": ["sim"],
                "sim_vision": "aruco",
                "sim_model": "x500_mono_cam_down",
                "sim_world": "marker_field",
            },
        },
    )
    from capabilities import _load, e2e_roster

    data = _load(reg)
    roster, excluded = e2e_roster(data, lambda entry: (True, ""))
    assert excluded == []
    assert roster == scenario_sim_configs("sim", registry=reg)
