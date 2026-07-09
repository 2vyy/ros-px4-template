"""Unit tests for ROS package manifest dependencies."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_PACKAGE_XML = _ROOT / "src" / "core" / "package.xml"


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
