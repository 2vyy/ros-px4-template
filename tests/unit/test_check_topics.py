"""Unit tests for check_topics dry-run (source grep) mode."""

from __future__ import annotations

from pathlib import Path

from check_topics import _topics_in_source


def test_finds_topic_in_source(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    (src / "node.py").write_text(
        'self.create_publisher(PoseStamped, "/drone/target_pose", qos)\n',
        encoding="utf-8",
    )
    found = _topics_in_source(["/drone/target_pose", "/missing/topic"], [src])
    assert "/drone/target_pose" in found
    assert "/missing/topic" not in found


def test_returns_empty_when_no_source_files(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    found = _topics_in_source(["/some/topic"], [empty])
    assert found == set()


def test_searches_nested_directories(tmp_path: Path) -> None:
    nested = tmp_path / "src" / "core" / "nodes"
    nested.mkdir(parents=True)
    (nested / "ctrl.py").write_text('"/fmu/in/trajectory_setpoint"', encoding="utf-8")
    found = _topics_in_source(["/fmu/in/trajectory_setpoint"], [tmp_path / "src"])
    assert "/fmu/in/trajectory_setpoint" in found


def test_nonexistent_source_root_is_skipped(tmp_path: Path) -> None:
    missing_dir = tmp_path / "does_not_exist"
    found = _topics_in_source(["/drone/pose_enu"], [missing_dir])
    assert found == set()
