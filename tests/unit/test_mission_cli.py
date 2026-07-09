"""Unit tests for the `just mission` CLI helpers (no Typer, no ROS)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

from ros_px4_template_core.lib.mission.loader import load_mission_file

from mission_cli import describe_mission, list_missions, mission_path, validate_mission


def test_list_missions_returns_all_four() -> None:
    missions = dict(list_missions())
    assert set(missions) >= {"hover", "demo", "marker_hover", "search_relocalize"}
    for name, comment in list_missions():
        assert comment, f"{name} has no description comment"


def test_validate_hover_ok() -> None:
    ok, msg = validate_mission("hover")
    assert ok
    assert "initial=hover" in msg


def test_validate_missing_file() -> None:
    ok, msg = validate_mission("__does_not_exist__")
    assert not ok
    assert "no such mission file" in msg


def test_validate_unknown_behavior(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        "mission:\n  initial: s0\n  states:\n    s0: {behavior: __nope__}\n  terminal: [s0]\n",
        encoding="utf-8",
    )
    ok, msg = validate_mission(str(bad))
    assert not ok
    assert msg.startswith("invalid:")
    assert "behavior" in msg


def test_validate_unknown_initial(tmp_path: Path) -> None:
    bad = tmp_path / "bad2.yaml"
    bad.write_text(
        "mission:\n  initial: ghost\n  states:\n    s0: {behavior: hold}\n  terminal: [s0]\n",
        encoding="utf-8",
    )
    ok, msg = validate_mission(str(bad))
    assert not ok
    assert msg.startswith("invalid:")
    assert "initial" in msg


def test_describe_hover_mentions_state_and_behavior() -> None:
    m = load_mission_file(mission_path("hover"))
    text = describe_mission(m)
    assert "hover" in text
    assert "hold" in text
