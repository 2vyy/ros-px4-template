"""Unit tests for the mission engine: tiers, determinism, single-transition, logging."""

from __future__ import annotations

import math

from ros_px4_template_core.lib import mission as _m  # noqa: F401
from ros_px4_template_core.lib.mission.commands import GoTo
from ros_px4_template_core.lib.mission.detection import Detection
from ros_px4_template_core.lib.mission.engine import MissionContext, tick
from ros_px4_template_core.lib.mission.types import Inputs, Mission, StateDef, TransitionDef


def _inputs(
    *,
    now: float = 0.0,
    pose_enu: tuple[float, float, float] = (0.0, 0.0, 3.0),
    yaw_enu: float = 0.0,
    armed: bool = True,
    altitude_ok: bool = True,
    estimate_ok: bool = True,
    detections: tuple[Detection, ...] = (),
    detection_stability: dict[int, int] | None = None,
    input_ages: dict[str, float] | None = None,
) -> Inputs:
    return Inputs(
        now=now,
        pose_enu=pose_enu,
        yaw_enu=yaw_enu,
        armed=armed,
        altitude_ok=altitude_ok,
        estimate_ok=estimate_ok,
        detections=detections,
        detection_stability={} if detection_stability is None else detection_stability,
        input_ages={"odom": 0.0} if input_ages is None else input_ages,
    )


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


def _precision_land_mission() -> Mission:
    return Mission(
        initial="descend",
        states={
            "descend": StateDef(
                "descend",
                "center_land",
                {"target_id": 0, "tolerance_m": 0.3, "descent_rate_m_s": 0.4},
            ),
            "reacquire": StateDef("reacquire", "hold", {}),
        },
        safety=(),
        transitions=(
            TransitionDef("descend", "marker_lost_signal", {}, "reacquire"),
            TransitionDef("reacquire", "marker_stable", {"id": 0, "n": 5}, "descend"),
        ),
        terminal=frozenset(),
    )


def _recovery_mission() -> Mission:
    """hold_safe has an outgoing mission edge, to show recovery once safety clears."""
    return Mission(
        initial="run",
        states={
            "run": StateDef("run", "hold", {"z": 3.0}),
            "hold_safe": StateDef("hold_safe", "hold", {}),
            "resumed": StateDef("resumed", "hold", {}),
        },
        safety=(TransitionDef(None, "estimate_invalid", {}, "hold_safe"),),
        transitions=(TransitionDef("hold_safe", "reached", {}, "resumed"),),
        terminal=frozenset({"resumed"}),
    )


def _self_loop_mission() -> Mission:
    return Mission(
        initial="spin",
        states={"spin": StateDef("spin", "hold", {"z": 3.0})},
        safety=(),
        transitions=(TransitionDef("spin", "reached", {}, "spin"),),
        terminal=frozenset(),
    )


def test_persistent_safety_does_not_re_enter_or_wipe_scratch() -> None:
    """A safety edge whose target is the current state is a no-op: no repeated
    TRANSITION event, and the hold target captured on entry FREEZES even as the
    live pose drifts (the fault-point-freeze property)."""
    ctx = MissionContext(state="takeoff")
    m = _mission()
    cmd1 = tick(ctx, m, _inputs(now=0.0, pose_enu=(1.0, 2.0, 3.0), estimate_ok=False))
    assert ctx.state == "hold_safe"
    assert isinstance(cmd1, GoTo)
    frozen = (cmd1.x, cmd1.y, cmd1.z)

    cmd2 = tick(ctx, m, _inputs(now=0.1, pose_enu=(5.0, 6.0, 3.0), estimate_ok=False))
    cmd3 = tick(ctx, m, _inputs(now=0.2, pose_enu=(9.0, 9.0, 3.0), estimate_ok=False))
    assert ctx.state == "hold_safe"
    assert isinstance(cmd2, GoTo)
    assert isinstance(cmd3, GoTo)
    assert (cmd2.x, cmd2.y, cmd2.z) == frozen
    assert (cmd3.x, cmd3.y, cmd3.z) == frozen

    evs = [e for e in ctx.events if e["event"] == "TRANSITION"]
    assert len(evs) == 1
    assert evs[0]["to"] == "hold_safe"


def test_safety_persists_suppresses_mission_tier_until_cleared() -> None:
    """While the safety condition holds, the mission tier stays suppressed; once
    it clears, the mission-tier edge out of hold_safe fires."""
    ctx = MissionContext(state="hold_safe")
    m = _recovery_mission()
    tick(ctx, m, _inputs(pose_enu=(0.0, 0.0, 3.0), estimate_ok=False))
    assert ctx.state == "hold_safe"  # reached=True, but safety suppresses the mission tier
    tick(ctx, m, _inputs(pose_enu=(0.0, 0.0, 3.0), estimate_ok=True))
    assert ctx.state == "resumed"


def test_mission_tier_self_loop_is_noop() -> None:
    ctx = MissionContext(state="spin")
    m = _self_loop_mission()
    for t in (0.0, 0.1, 0.2):
        tick(ctx, m, _inputs(now=t, pose_enu=(0.0, 0.0, 3.0)))
    assert ctx.state == "spin"
    assert not [e for e in ctx.events if e["event"] == "TRANSITION"]
    assert ctx.scratch.get("spin")  # scratch survived, not wiped every tick


def test_simulate_persistent_safety_logs_one_transition() -> None:
    """End to end over demo.yaml: a lost estimate held from t=5 s logs exactly
    one hold_safe TRANSITION, not one per tick (the churn this plan fixes)."""
    from pathlib import Path

    from ros_px4_template_core.lib.mission.loader import load_mission_file
    from ros_px4_template_core.lib.mission.simulate import SimVehicle, simulate

    demo = Path(__file__).resolve().parents[2] / "config" / "missions" / "demo.yaml"
    m = load_mission_file(demo)

    def script(now: float, v: SimVehicle) -> None:
        if now >= 5.0:
            v.estimate_ok = False

    result = simulate(m, max_ticks=200, script=script)
    to_safe = [e for e in result.events if e.get("to") == "hold_safe"]
    assert len(to_safe) == 1


def test_reentry_reinitializes_descend_scratch_from_current_altitude() -> None:
    """Re-entering `descend` after a `reacquire` detour must not carry over the
    previous episode's z_cmd -- it re-derives descent from the CURRENT pose,
    per plan 042's addendum (scratch clears on every transition)."""
    ctx = MissionContext(state="descend")
    mission = _precision_land_mission()
    det = Detection(id=0, offset_body_flu=(0.0, 0.0, -5.0), stamp=0.0)
    # Descend for a few ticks at high altitude, centered and fresh.
    for t in (0.0, 0.1, 0.2):
        cmd = tick(
            ctx,
            mission,
            _inputs(now=t, pose_enu=(0.0, 0.0, 5.0), detections=(det,), armed=True),
        )
    assert isinstance(cmd, GoTo)
    assert cmd.z < 5.0  # it has descended from the initial 5.0m

    # Marker disappears -> transitions to reacquire (holds current pose).
    cmd = tick(ctx, mission, _inputs(now=1.5, pose_enu=(0.0, 0.0, cmd.z), detections=()))
    assert ctx.state == "reacquire"

    # Marker reacquired and stable -> transitions back to descend. The vehicle
    # is now much lower (2.0m) than the previous episode's z_cmd; re-entry must
    # re-derive from THIS altitude, not silently jump/continue the old one.
    stable_det = Detection(id=0, offset_body_flu=(0.0, 0.0, -2.0), stamp=1.5)
    cmd = tick(
        ctx,
        mission,
        _inputs(
            now=1.5,
            pose_enu=(0.0, 0.0, 2.0),
            detections=(stable_det,),
            detection_stability={0: 5},
        ),
    )
    assert ctx.state == "descend"
    assert isinstance(cmd, GoTo)
    assert math.isclose(cmd.z, 2.0, abs_tol=1e-9)
