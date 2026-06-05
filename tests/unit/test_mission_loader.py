"""Unit tests for the mission YAML loader + validation."""

from __future__ import annotations

import pytest
from ros_px4_template_core.lib import mission as _m  # noqa: F401
from ros_px4_template_core.lib.mission.loader import MissionError, load_mission_dict


def _doc() -> dict:
    return {
        "mission": {
            "initial": "takeoff",
            "safety": [{"guard": "estimate_invalid", "to": "hold_safe"}],
            "states": {
                "takeoff": {"behavior": "hold", "params": {"z": 3.0}},
                "follow": {
                    "behavior": "follow_waypoints",
                    "params": {"waypoints": [[5.0, 0.0, 3.0]]},
                },
                "done": {"behavior": "hold"},
                "hold_safe": {"behavior": "hold"},
            },
            "transitions": [
                {"from": "takeoff", "guard": "armed_at_altitude", "to": "follow"},
                {"from": "follow", "guard": "waypoints_done", "to": "done"},
            ],
            "terminal": ["done"],
        }
    }


def test_load_valid_mission() -> None:
    m = load_mission_dict(_doc())
    assert m.initial == "takeoff"
    assert set(m.states) == {"takeoff", "follow", "done", "hold_safe"}
    assert m.safety[0].src is None
    assert m.safety[0].dst == "hold_safe"
    assert m.transitions[0].src == "takeoff"
    assert m.terminal == frozenset({"done"})


def test_unknown_behavior_rejected() -> None:
    doc = _doc()
    doc["mission"]["states"]["takeoff"]["behavior"] = "nope"
    with pytest.raises(MissionError, match="behavior"):
        load_mission_dict(doc)


def test_unknown_guard_rejected() -> None:
    doc = _doc()
    doc["mission"]["transitions"][0]["guard"] = "nope"
    with pytest.raises(MissionError, match="guard"):
        load_mission_dict(doc)


def test_unknown_transition_target_rejected() -> None:
    doc = _doc()
    doc["mission"]["transitions"][0]["to"] = "ghost"
    with pytest.raises(MissionError, match="target"):
        load_mission_dict(doc)


def test_unknown_initial_rejected() -> None:
    doc = _doc()
    doc["mission"]["initial"] = "ghost"
    with pytest.raises(MissionError, match="initial"):
        load_mission_dict(doc)
