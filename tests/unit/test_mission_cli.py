"""Unit tests for the `just mission` CLI helpers (no Typer, no ROS)."""

from __future__ import annotations

import sys
from pathlib import Path

from typer.testing import CliRunner

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

from ros_px4_template_core.lib.mission.loader import load_mission_file

from mission_cli import app as mission_app
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


def test_validate_unknown_required_claim(tmp_path: Path, monkeypatch) -> None:
    mission = tmp_path / "needs_claim.yaml"
    mission.write_text(
        "requires: [ghost_claim]\n"
        "mission:\n"
        "  initial: s0\n"
        "  states:\n"
        "    s0: {behavior: hold}\n"
        "  terminal: [s0]\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "capabilities._load",
        lambda registry=None: {
            "capabilities": {
                "arm_takeoff": {
                    "description": "d",
                    "scenario_file": "01_arm_takeoff.py",
                    "platforms": ["sim"],
                }
            }
        },
    )
    runner = CliRunner()
    result = runner.invoke(mission_app, ["validate", str(mission)])
    assert result.exit_code == 2
    assert "UNKNOWN CLAIM(S) in requires: ghost_claim" in result.output


def test_sim_require_terminal_rejects_terminal_less_mission(tmp_path: Path) -> None:
    mission = tmp_path / "steady.yaml"
    mission.write_text(
        "mission:\n  initial: hover\n  states:\n    hover: {behavior: hold, params: {z: 3.0}}\n",
        encoding="utf-8",
    )
    runner = CliRunner()

    assert runner.invoke(mission_app, ["sim", str(mission)]).exit_code == 0
    required = runner.invoke(
        mission_app,
        ["sim", str(mission), "--require-terminal"],
    )

    assert required.exit_code == 1
    assert "terminal" in required.output
