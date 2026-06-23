"""Unit tests for the scenario scaffold renderer (pure, no ROS)."""

from __future__ import annotations

import ast

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
