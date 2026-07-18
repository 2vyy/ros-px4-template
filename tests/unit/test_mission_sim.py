"""Engine-level simulation of the real mission YAMLs (plan 054).

Proves each mission's GRAPH progresses: the happy path reaches a terminal
state, guards fire when their conditions occur, and a bad guard stalls. Runs
the pure engine over a kinematic model -- no sim boot -- so a NEW mission gets
this coverage for free (the happy-path test globs config/missions/).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from ros_px4_template_core.lib.mission.loader import load_mission_dict, load_mission_file
from ros_px4_template_core.lib.mission.simulate import (
    SimVehicle,
    marker_at_script,
    marker_below_script,
    simulate,
)
from ros_px4_template_core.lib.mission.types import Mission

_MISSIONS_DIR = Path(__file__).resolve().parents[2] / "config" / "missions"
_MISSION_FILES = sorted(_MISSIONS_DIR.glob("*.yaml"))


def _wants_marker(mission: Mission) -> bool:
    """Mirror the `just mission sim` heuristic: any marker/center behavior."""
    return any("marker" in sd.behavior or "center" in sd.behavior for sd in mission.states.values())


def _auto_script(mission: Mission) -> Callable[[float, SimVehicle], None] | None:
    return marker_below_script() if _wants_marker(mission) else None


def _load(name: str) -> Mission:
    return load_mission_file(_MISSIONS_DIR / f"{name}.yaml")


# ── Every real mission progresses to a terminal state ─────────────────────────


def test_missions_dir_is_globbed() -> None:
    """Guard: a new mission file must land in the parametrized happy-path test."""
    assert _MISSION_FILES, f"no mission YAMLs found under {_MISSIONS_DIR}"


@pytest.mark.parametrize("path", _MISSION_FILES, ids=lambda p: p.stem)
def test_real_mission_reaches_terminal(path: Path) -> None:
    """Each config/missions/*.yaml walks its happy path to a terminal state."""
    mission = load_mission_file(path)
    result = simulate(mission, script=_auto_script(mission))
    assert result.terminated, (
        f"{path.stem} did not terminate in {result.ticks} ticks; "
        f"stuck in {result.final_state}, reached {result.reached_states}"
    )
    assert result.final_state in mission.terminal


# ── Per-mission specifics (derived from each YAML at 01f94c7) ─────────────────


def test_demo_walks_takeoff_follow_done() -> None:
    result = simulate(_load("demo"))
    assert result.reached_states == ["takeoff", "follow", "done"]
    assert result.terminated


def test_hover_is_terminal_at_start() -> None:
    """hover.yaml's initial state IS its terminal state (terminal: [hover])."""
    result = simulate(_load("hover"))
    assert result.final_state == "hover"
    assert result.terminated


def test_yaw_demo_reaches_yaw_hold() -> None:
    result = simulate(_load("yaw_demo"))
    assert result.reached_states == ["takeoff", "yaw_hold"]
    assert result.terminated


def test_marker_hover_reaches_marker_hover() -> None:
    mission = _load("marker_hover")
    result = simulate(mission, script=marker_below_script())
    assert "marker_hover" in result.reached_states
    assert result.terminated  # hold_complete after the 10 s center hold -> done


def test_search_relocalize_relocalizes_and_returns() -> None:
    mission = _load("search_relocalize")
    result = simulate(mission, script=marker_below_script())
    assert result.terminated
    assert "return_to_origin" in result.reached_states


def test_precision_land_descends_and_lands_on_the_marker() -> None:
    """The marker sits at the approach waypoint; the drone must fly there and
    converge before center_land descends -- exercising the offset geometry."""
    mission = _load("precision_land")
    result = simulate(mission, script=marker_at_script((8.0, 0.0, 0.0)))
    assert result.landed
    assert "descend" in result.reached_states
    assert result.terminated  # disarmed after PX4 hand-off -> done
    # Landed on the marker, not at the origin: proves the body-FLU offset sign.
    assert abs(result.final_pose[0] - 8.0) < 0.5
    assert abs(result.final_pose[1] - 0.0) < 0.5


# ── Negative cases: the harness catches real authoring errors ─────────────────


def _stalling_mission_dict() -> dict:
    """A hold state whose only exit guard (waypoints_done) hold never emits."""
    return {
        "mission": {
            "initial": "hover",
            "states": {
                "hover": {"behavior": "hold", "params": {"z": 3.0}},
                "done": {"behavior": "hold"},
            },
            "transitions": [{"from": "hover", "guard": "waypoints_done", "to": "done"}],
            "terminal": ["done"],
        }
    }


def test_stall_is_reported_not_a_false_pass() -> None:
    mission = load_mission_dict(_stalling_mission_dict())
    result = simulate(mission, max_ticks=200)
    assert not result.terminated
    assert result.final_state == "hover"


def test_safety_diversion_on_lost_estimate() -> None:
    """estimate_ok=False mid-flight diverts demo to its hold_safe safety sink."""
    mission = _load("demo")

    def script(now: float, v: SimVehicle) -> None:
        if now >= 5.0:
            v.estimate_ok = False

    result = simulate(mission, max_ticks=200, script=script)
    assert result.final_state == "hold_safe"
    assert not result.terminated


def test_time_budget_safety_transition_uses_simulated_armed_time() -> None:
    mission = load_mission_dict(
        {
            "mission": {
                "initial": "fly",
                "safety": [
                    {
                        "guard": "time_budget",
                        "params": {"budget_s": 2.0},
                        "to": "land",
                    }
                ],
                "states": {
                    "fly": {"behavior": "hold", "params": {"z": 3.0}},
                    "land": {"behavior": "hold"},
                },
                "terminal": ["land"],
            }
        }
    )

    result = simulate(mission, tick_rate_hz=10.0, max_ticks=30)

    assert result.final_state == "land"
    assert result.terminated
    assert 2.0 < result.ticks / 10.0 <= 2.2
