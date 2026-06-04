"""Unit tests for mission_runtime tick()."""

from __future__ import annotations

from pathlib import Path

import pytest
from ros_px4_template_core.lib.mission_profile import MissionProfileParams, build_mission_profile
from ros_px4_template_core.lib.mission_runtime import (
    PHASE_DONE,
    PHASE_FOLLOW_PATH,
    PHASE_MARKER_HOVER,
    MissionContext,
    TickInputs,
    tick,
)
from ros_px4_template_core.lib.waypoint_mission import EnuPoint, load_path_yaml

DEMO_PATH = Path(__file__).resolve().parents[2] / "config/paths/demo.yaml"


def _demo_mission():
    return build_mission_profile(load_path_yaml(DEMO_PATH), MissionProfileParams())


def _inputs(
    *,
    pos: tuple[float, float, float] = (0.0, 0.0, 0.0),
    armed: bool = True,
    altitude_ok: bool = True,
    now: float = 0.0,
    marker_offset_enu: tuple[float, float] | None = None,
    marker_hold_s: float = 10.0,
) -> TickInputs:
    return TickInputs(
        now=now,
        pos_enu=pos,
        controller_armed=armed,
        altitude_ok=altitude_ok,
        marker_offset_enu=marker_offset_enu,
        marker_hold_s=marker_hold_s,
    )


def test_wait_to_follow_path() -> None:
    mission = _demo_mission()
    ctx = MissionContext()
    out = tick(ctx, mission, _inputs(pos=(0, 0, 0), armed=True, altitude_ok=True))
    assert out.phase == PHASE_FOLLOW_PATH


def test_follow_path_transitions_to_done_without_marker() -> None:
    mission = _demo_mission()
    ctx = MissionContext()
    ctx.phase = PHASE_FOLLOW_PATH
    ctx.waypoint_index = len(mission.waypoints) - 1
    last_wp = mission.waypoints[-1]

    tick(ctx, mission, _inputs(pos=(last_wp.x, last_wp.y, last_wp.z), now=0.0))
    t1 = mission.defaults.hold_s + 1.0
    tick(
        ctx,
        mission,
        _inputs(
            pos=(last_wp.x, last_wp.y, last_wp.z),
            now=t1,
            marker_offset_enu=None,
        ),
    )
    assert ctx.phase == PHASE_FOLLOW_PATH

    out = tick(
        ctx,
        mission,
        _inputs(
            pos=(last_wp.x, last_wp.y, last_wp.z),
            now=t1 + 2.1,
            marker_offset_enu=None,
        ),
    )
    assert out.phase == PHASE_DONE


def test_follow_path_transitions_to_marker_hover_when_marker_visible() -> None:
    mission = _demo_mission()
    ctx = MissionContext()
    ctx.phase = PHASE_FOLLOW_PATH
    ctx.waypoint_index = len(mission.waypoints) - 1
    last_wp = mission.waypoints[-1]

    tick(ctx, mission, _inputs(pos=(last_wp.x, last_wp.y, last_wp.z), now=0.0))
    out = tick(
        ctx,
        mission,
        _inputs(
            pos=(last_wp.x, last_wp.y, last_wp.z),
            now=mission.defaults.hold_s + 1.0,
            marker_offset_enu=(0.5, -0.3),
        ),
    )
    assert out.phase == PHASE_MARKER_HOVER


def test_marker_hover_updates_target_with_offset() -> None:
    mission = _demo_mission()
    ctx = MissionContext()
    ctx.phase = PHASE_MARKER_HOVER
    ctx.target = EnuPoint(5.0, 5.0, 3.0)

    out = tick(
        ctx,
        mission,
        _inputs(
            pos=(5.0, 5.0, 3.0),
            now=0.0,
            marker_offset_enu=(1.0, -0.5),
            marker_hold_s=10.0,
        ),
    )
    assert out.target.x == pytest.approx(6.0)
    assert out.target.y == pytest.approx(4.5)
    assert out.target.z == pytest.approx(3.0)


def test_marker_hover_transitions_to_done_after_hold() -> None:
    mission = _demo_mission()
    ctx = MissionContext()
    ctx.phase = PHASE_MARKER_HOVER
    ctx.target = EnuPoint(0.0, 0.0, 3.0)

    tick(ctx, mission, _inputs(pos=(0.0, 0.0, 3.0), now=0.0, marker_hold_s=5.0))
    out = tick(
        ctx,
        mission,
        _inputs(pos=(0.0, 0.0, 3.0), now=6.0, marker_hold_s=5.0),
    )
    assert out.phase == PHASE_DONE
