"""Claims DAG frontier tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

import cap_evidence
import capabilities
from cap_plan import format_plan, next_action, topo_order
from cap_status import RungInfo


def _reg() -> dict:
    return {
        "capabilities": {
            "arm_takeoff": {
                "description": "d",
                "platforms": ["sim"],
                "scenario_file": "01_arm_takeoff.py",
                "requires": [],
            },
            "rover_follow": {
                "description": "d",
                "platforms": ["sim"],
                "scenario_file": "10_rover_follow.py",
                "requires": ["arm_takeoff"],
            },
            "challenge_2": {
                "description": "d",
                "requires": ["rover_follow"],
            },
        }
    }


def test_topo_order_puts_dependencies_first() -> None:
    order = topo_order(_reg())
    assert order.index("arm_takeoff") < order.index("rover_follow")
    assert order.index("rover_follow") < order.index("challenge_2")


def test_topo_order_preserves_registry_order_among_ties() -> None:
    registry = {
        "capabilities": {
            "b": {"description": "d", "requires": []},
            "a": {"description": "d", "requires": []},
        }
    }
    assert topo_order(registry) == ["b", "a"]


def test_next_action_scaffold_when_scenario_missing() -> None:
    entry = _reg()["capabilities"]["rover_follow"]
    action = next_action(
        "rover_follow",
        entry,
        RungInfo(
            "declared",
            reason="scenario missing: tests/scenarios/10_rover_follow.py",
        ),
    )
    assert action == "just scenario-new 10_rover_follow"


def test_next_action_mission_sim_when_mission_failing() -> None:
    entry = {
        "description": "d",
        "scenario_file": "s.py",
        "mission": "hover",
        "requires": [],
    }
    action = next_action(
        "x",
        entry,
        RungInfo(
            "declared",
            reason="mission sim failing: hover (run: just mission sim hover)",
        ),
    )
    assert action == "just mission sim hover --require-terminal"


def test_next_action_fly_when_simulated_or_stale() -> None:
    entry = _reg()["capabilities"]["arm_takeoff"]
    assert next_action("arm_takeoff", entry, RungInfo("simulated")) == (
        "just scenario 01_arm_takeoff"
    )
    assert next_action("arm_takeoff", entry, RungInfo("sim-flown-stale")) == (
        "just scenario 01_arm_takeoff"
    )


def test_format_plan_complete_when_all_flown() -> None:
    infos = {name: RungInfo("sim-flown") for name in _reg()["capabilities"]}
    text, complete = format_plan(_reg(), infos, None)
    assert complete
    assert "LADDER COMPLETE" in text


def test_format_plan_scopes_to_target_closure() -> None:
    infos = {
        "arm_takeoff": RungInfo("sim-flown"),
        "rover_follow": RungInfo("simulated"),
        "challenge_2": RungInfo("simulated"),
    }
    text, complete = format_plan(_reg(), infos, "challenge_2")
    assert not complete
    assert "rover_follow" in text
    assert "arm_takeoff" not in text


def test_plan_unknown_claim_is_usage_error() -> None:
    result = CliRunner().invoke(capabilities.app, ["plan", "ghost"])
    assert result.exit_code == 2
    assert "NO SUCH CLAIM: ghost" in result.output


@pytest.mark.parametrize("command", [["show"], ["plan"]])
def test_derived_commands_reject_invalid_registry(
    command: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    invalid = {
        "capabilities": {
            "broken": {
                "description": "d",
                "requires": ["ghost"],
            }
        }
    }
    monkeypatch.setattr(capabilities, "_load", lambda: invalid)

    result = CliRunner().invoke(capabilities.app, command)

    assert result.exit_code == 2
    assert "REGISTRY INVALID" in result.output
    assert "ghost" in result.output


@pytest.mark.parametrize("contents", [None, "[capabilities"])
def test_show_rejects_missing_or_malformed_registry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    contents: str | None,
) -> None:
    registry = tmp_path / "capabilities.toml"
    if contents is not None:
        registry.write_text(contents)
    monkeypatch.setattr(capabilities, "REGISTRY", registry)

    result = CliRunner().invoke(capabilities.app, ["show"])

    assert result.exit_code == 2
    assert "REGISTRY INVALID" in result.output


def test_show_ignores_uncommitted_evidence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    registry = {
        "capabilities": {
            "arm_takeoff": {
                "description": "d",
                "requires": [],
                "platforms": ["sim"],
                "scenario_file": "01_arm_takeoff.py",
            }
        }
    }
    directory = tmp_path / "arm_takeoff"
    directory.mkdir()
    (directory / "20260717_000000_sim.json").write_text(
        json.dumps(
            {
                "claim": "arm_takeoff",
                "platform": "sim",
                "commit": "abc1234",
                "run_id": "20260717_000000",
                "verdict": "PASS",
            }
        )
    )
    monkeypatch.setattr(capabilities, "_load", lambda: registry)
    monkeypatch.setattr(cap_evidence, "EVIDENCE_ROOT", tmp_path)
    monkeypatch.setattr(
        cap_evidence,
        "real_evidence_committed",
        lambda path: False,
    )

    result = CliRunner().invoke(capabilities.app, ["show"])

    assert result.exit_code == 0
    assert "uncommitted evidence skipped" in result.output
    assert "evidence 0" not in result.output
