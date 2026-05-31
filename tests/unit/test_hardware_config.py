# tests/unit/test_hardware_config.py
"""Validate hardware config files parse correctly."""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def _load(rel: str) -> dict:
    return yaml.safe_load((ROOT / rel).read_text()) or {}


def test_hardware_yaml_exists() -> None:
    assert (ROOT / "config" / "params" / "hardware.yaml").is_file()


def test_hardware_yaml_parses() -> None:
    data = _load("config/params/hardware.yaml")
    assert isinstance(data, dict)


def test_hardware_yaml_has_offboard_controller_section() -> None:
    data = _load("config/params/hardware.yaml")
    assert "offboard_controller" in data
    params = data["offboard_controller"]["ros__parameters"]
    assert "auto_arm" in params
    assert params["auto_arm"] is False, "hardware must default to manual arm for safety"


def test_vehicle_x500_yaml_exists() -> None:
    assert (ROOT / "vehicles" / "x500.yaml").is_file()


def test_vehicle_x500_yaml_parses() -> None:
    data = _load("vehicles/x500.yaml")
    assert isinstance(data, dict)
