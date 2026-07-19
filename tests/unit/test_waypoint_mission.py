"""Unit tests for waypoint_mission."""

from __future__ import annotations

from pathlib import Path

import pytest
from ros_px4_template_core.lib.waypoint_mission import load_path_yaml

DEMO_PATH = Path(__file__).resolve().parents[2] / "config/paths/demo.yaml"


def test_load_path_demo_list() -> None:
    wps = load_path_yaml(DEMO_PATH)
    assert len(wps) == 3
    assert wps[0].z == 3.0


def test_load_path_empty_raises() -> None:
    bad = Path(__file__).resolve().parents[2] / "config/paths/_test_empty.yaml"
    bad.write_text("[]\n")
    try:
        with pytest.raises(ValueError, match="at least one waypoint"):
            load_path_yaml(bad)
    finally:
        bad.unlink(missing_ok=True)


def test_load_path_nan_raises() -> None:
    bad = Path(__file__).resolve().parents[2] / "config/paths/_test_nan.yaml"
    bad.write_text("- {x: 1.0, y: 0.0, z: .nan}\n")
    try:
        with pytest.raises(ValueError, match="finite"):
            load_path_yaml(bad)
    finally:
        bad.unlink(missing_ok=True)


def test_load_path_inf_raises() -> None:
    bad = Path(__file__).resolve().parents[2] / "config/paths/_test_inf.yaml"
    bad.write_text("- {x: 1.0, y: .inf, z: 2.0}\n")
    try:
        with pytest.raises(ValueError, match="finite"):
            load_path_yaml(bad)
    finally:
        bad.unlink(missing_ok=True)
