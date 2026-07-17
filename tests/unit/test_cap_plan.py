"""Claims DAG frontier tests."""

from __future__ import annotations

from typer.testing import CliRunner

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
    assert action == "just mission sim hover"


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
