"""Unit tests for the mission engine: tiers, determinism, single-transition, logging."""

from __future__ import annotations

from ros_px4_template_core.lib import mission as _m  # noqa: F401
from ros_px4_template_core.lib.mission.commands import GoTo
from ros_px4_template_core.lib.mission.engine import MissionContext, tick
from ros_px4_template_core.lib.mission.types import Inputs, Mission, StateDef, TransitionDef


def _inputs(**kw) -> Inputs:
    base = dict(
        now=0.0,
        pose_enu=(0.0, 0.0, 3.0),
        yaw_enu=0.0,
        armed=True,
        altitude_ok=True,
        estimate_ok=True,
        detections=(),
        detection_stability={},
        input_ages={"odom": 0.0},
    )
    base.update(kw)
    return Inputs(**base)


def _mission() -> Mission:
    return Mission(
        initial="takeoff",
        states={
            "takeoff": StateDef("takeoff", "hold", {"z": 3.0}),
            "follow": StateDef("follow", "follow_waypoints", {"waypoints": [(5.0, 0.0, 3.0)]}),
            "done": StateDef("done", "hold", {}),
            "hold_safe": StateDef("hold_safe", "hold", {}),
        },
        safety=(TransitionDef(None, "estimate_invalid", {}, "hold_safe"),),
        transitions=(
            TransitionDef("takeoff", "armed_at_altitude", {}, "follow"),
            TransitionDef("follow", "waypoints_done", {}, "done"),
        ),
        terminal=frozenset({"done"}),
    )


def test_mission_transition_logs_and_advances() -> None:
    ctx = MissionContext(state="takeoff")
    cmd = tick(ctx, _mission(), _inputs(armed=True, altitude_ok=True))
    assert ctx.state == "follow"
    assert isinstance(cmd, GoTo)
    assert (cmd.x, cmd.y) == (5.0, 0.0)
    evs = [e for e in ctx.events if e["event"] == "TRANSITION"]
    assert evs
    assert evs[0]["from"] == "takeoff"
    assert evs[0]["to"] == "follow"
    assert evs[0]["tier"] == "mission"


def test_safety_tier_preempts_mission_tier() -> None:
    ctx = MissionContext(state="takeoff")
    tick(ctx, _mission(), _inputs(armed=True, altitude_ok=True, estimate_ok=False))
    assert ctx.state == "hold_safe"
    evs = [e for e in ctx.events if e["event"] == "TRANSITION"]
    assert evs[0]["tier"] == "safety"


def test_at_most_one_transition_per_tick() -> None:
    ctx = MissionContext(state="takeoff")
    tick(ctx, _mission(), _inputs(armed=True, altitude_ok=True))
    assert ctx.state == "follow"


def test_terminal_state_skips_mission_tier_but_keeps_safety() -> None:
    ctx = MissionContext(state="done")
    tick(ctx, _mission(), _inputs(estimate_ok=False))
    assert ctx.state == "hold_safe"
    ctx2 = MissionContext(state="done")
    cmd = tick(ctx2, _mission(), _inputs())
    assert ctx2.state == "done"
    assert isinstance(cmd, GoTo)


def test_entry_resets_scratch() -> None:
    ctx = MissionContext(state="takeoff")
    tick(ctx, _mission(), _inputs(armed=True, altitude_ok=True))
    assert "follow" in ctx.scratch
    assert ctx.scratch.get("takeoff", {}) == {} or "takeoff" not in ctx.scratch
