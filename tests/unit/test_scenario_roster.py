"""The scenario roster: files in tests/scenarios/ <-> declarations in capabilities.toml."""

from __future__ import annotations

from pathlib import Path

from capabilities import scenario_sim_configs

ROOT = Path(__file__).resolve().parents[2]


def scenarios_for_platform(platform: str) -> list[str]:
    return [c["scenario"] for c in scenario_sim_configs(platform)]


def _scenario_files() -> set[str]:
    return {p.stem for p in (ROOT / "tests" / "scenarios").glob("[0-9][0-9]_*.py")}


def test_every_scenario_file_is_declared_for_sim() -> None:
    files = _scenario_files()
    declared = set(scenarios_for_platform("sim"))
    assert files - declared == set(), (
        f"scenario files not declared in tests/capabilities.toml (platforms must "
        f"include 'sim'): {sorted(files - declared)}"
    )


def test_every_declared_scenario_has_a_file() -> None:
    files = _scenario_files()
    declared = set(scenarios_for_platform("sim"))
    assert declared - files == set(), (
        f"capabilities.toml declares scenarios with no file: {sorted(declared - files)}"
    )
