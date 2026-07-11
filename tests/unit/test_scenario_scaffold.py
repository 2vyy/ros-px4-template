"""Unit tests for the scenario scaffold renderer (pure, no ROS)."""

from __future__ import annotations

import ast
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import tasks
from typer.testing import CliRunner

from scenario_scaffold import class_name, render_scenario


def test_rendered_stub_parses() -> None:
    ast.parse(render_scenario("99_smoke"))


def test_rendered_stub_contains_key_symbols() -> None:
    src = render_scenario("99_smoke")
    assert "from _common import Scenario, run_main" in src
    assert "class SmokeScenario(Scenario):" in src
    assert 'name = "99_smoke"' in src
    assert "run_main(SmokeScenario)" in src
    assert 'super().__init__("scenario_99_smoke")' in src


def test_class_name_strips_leading_number() -> None:
    assert class_name("99_smoke") == "Smoke"
    assert class_name("12_foo_bar") == "FooBar"
    assert class_name("plain") == "Plain"


def test_scenario_new_snippet_declares_sim_platform(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "tests" / "scenarios").mkdir(parents=True)
    monkeypatch.setattr(tasks, "ROOT", tmp_path)
    result = CliRunner().invoke(tasks.app, ["scenario-new", "99_snippet"])
    assert result.exit_code == 0, result.output
    assert 'platforms = ["sim"]' in result.output
    assert "platforms = []" not in result.output
    assert (tmp_path / "tests" / "scenarios" / "99_snippet.py").exists()
