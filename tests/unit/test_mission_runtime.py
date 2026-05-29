"""Unit tests for mission_runtime tick()."""

from __future__ import annotations

from pathlib import Path

from ros_px4_template_core.lib.mission_profile import MissionProfileParams, build_mission_profile
from ros_px4_template_core.lib.mission_runtime import (
    PHASE_DONE,
    PHASE_FOLLOW_PATH,
    PHASE_HOVER_MARKER,
    MissionContext,
    TickInputs,
    tick,
)
from ros_px4_template_core.lib.waypoint_mission import EnuPoint, load_path_yaml

DEMO_PATH = Path(__file__).resolve().parents[2] / "config/paths/demo.yaml"


def _inspect_mission():
    return build_mission_profile(
        load_path_yaml(DEMO_PATH),
        MissionProfileParams(enable_marker_hover=True),
    )


def test_wait_to_follow_path() -> None:
    mission = _inspect_mission()
    ctx = MissionContext()
    out = tick(
        ctx,
        mission,
        TickInputs(
            now=0.0,
            pos_enu=(0, 0, 0),
            controller_armed=True,
            altitude_ok=True,
            marker_valid=False,
            marker_position=None,
        ),
    )
    assert out.phase == PHASE_FOLLOW_PATH


def test_marker_triggers_hover() -> None:
    mission = _inspect_mission()
    ctx = MissionContext(phase=PHASE_FOLLOW_PATH, waypoint_index=2)
    for i in range(5):
        tick(
            ctx,
            mission,
            TickInputs(
                now=float(i),
                pos_enu=(8, 0, 3),
                controller_armed=True,
                altitude_ok=True,
                marker_valid=True,
                marker_position=(8.0, 0.0, 0.0),
            ),
        )
    assert ctx.phase == PHASE_HOVER_MARKER


def test_path_complete_then_marker_next_tick() -> None:
    """B14: after last waypoint, marker on a later tick still enters hover_marker."""
    mission = build_mission_profile(
        [EnuPoint(1.0, 0.0, 3.0)],
        MissionProfileParams(enable_marker_hover=True, hold_s=0.0, marker_acquire_frames=3),
    )
    ctx = MissionContext(phase=PHASE_FOLLOW_PATH, waypoint_index=0)
    for t in (0.0, 0.1):
        tick(
            ctx,
            mission,
            TickInputs(
                now=t,
                pos_enu=(1.0, 0.0, 3.0),
                controller_armed=True,
                altitude_ok=True,
                marker_valid=False,
                marker_position=None,
            ),
        )
    assert ctx.waypoint_index == 1
    assert ctx.phase == PHASE_FOLLOW_PATH
    for i in range(3):
        tick(
            ctx,
            mission,
            TickInputs(
                now=float(i + 1),
                pos_enu=(1.0, 0.0, 3.0),
                controller_armed=True,
                altitude_ok=True,
                marker_valid=True,
                marker_position=(1.0, 0.0, 0.0),
            ),
        )
    assert ctx.phase == PHASE_HOVER_MARKER


def test_done_after_hold() -> None:
    mission = _inspect_mission()
    ctx = MissionContext(phase=PHASE_HOVER_MARKER, hover_start=0.0)
    ctx.target = mission.waypoints[-1]
    out = tick(
        ctx,
        mission,
        TickInputs(
            now=31.0,
            pos_enu=(8, 0, 1.5),
            controller_armed=True,
            altitude_ok=True,
            marker_valid=True,
            marker_position=(8.0, 0.0, 0.0),
        ),
    )
    assert out.phase == PHASE_DONE
