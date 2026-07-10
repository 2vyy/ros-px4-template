"""Unit tests for ROS package manifest dependencies and installed resources."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_PACKAGE_XML = _ROOT / "src" / "core" / "package.xml"
_SETUP_PY = _ROOT / "src" / "core" / "setup.py"


def _dependency_names(tag: str) -> set[str]:
    root = ET.parse(_PACKAGE_XML).getroot()
    return {elem.text or "" for elem in root.findall(tag)}


def test_launch_runtime_dependencies_are_declared() -> None:
    exec_deps = _dependency_names("exec_depend")

    assert "ros2launch" in exec_deps
    assert "rosbridge_server" in exec_deps
    assert "ros_gz_bridge" in exec_deps
    assert "ros_gz_sim" in exec_deps
    assert "cv_bridge" in exec_deps


def test_core_python_runtime_dependencies_are_declared() -> None:
    deps = _dependency_names("depend")

    assert "ament_index_python" in deps
    assert "python3-numpy" in deps
    assert "python3-yaml" in deps
    assert "python3-opencv" in deps


def test_marker_maps_are_installed_as_a_package_resource() -> None:
    """setup.py must install config/marker_maps/*.yaml so the package share dir
    carries world-specific marker maps (e.g. marker_field.yaml) after a build."""
    setup_text = _SETUP_PY.read_text(encoding="utf-8")

    assert "config/marker_maps" in setup_text
    assert '"../../config/marker_maps/*.yaml"' in setup_text

    marker_maps_dir = _ROOT / "config" / "marker_maps"
    assert marker_maps_dir.is_dir()
    assert list(marker_maps_dir.glob("*.yaml")), "expected at least one committed marker map"
