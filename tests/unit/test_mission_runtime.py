"""Unit tests for mission_runtime tick()."""

from __future__ import annotations

from pathlib import Path

from ros_px4_template_core.lib.mission_runtime import (
    PHASE_DONE,
    PHASE_FOLLOW_PATH,
    PHASE_HOVER_MARKER,
    MissionContext,
    TickInputs,
    tick,
)
from ros_px4_template_core.lib.waypoint_mission import load_mission_yaml

MISSION = Path(__file__).resolve().parents[2] / "config/missions/inspect_aruco.yaml"


def test_wait_to_follow_path() -> None:
    mission = load_mission_yaml(MISSION)
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
    mission = load_mission_yaml(MISSION)
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


def test_done_after_hold() -> None:
    mission = load_mission_yaml(MISSION)
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
