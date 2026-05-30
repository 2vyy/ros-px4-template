"""Unit tests for mission_runtime tick()."""

from __future__ import annotations

from pathlib import Path

from ros_px4_template_core.lib.mission_profile import MissionProfileParams, build_mission_profile
from ros_px4_template_core.lib.mission_runtime import (
    PHASE_DONE,
    PHASE_FOLLOW_PATH,
    MissionContext,
    TickInputs,
    tick,
)
from ros_px4_template_core.lib.waypoint_mission import EnuPoint, load_path_yaml

DEMO_PATH = Path(__file__).resolve().parents[2] / "config/paths/demo.yaml"


def _demo_mission():
    return build_mission_profile(load_path_yaml(DEMO_PATH), MissionProfileParams())


def _inputs(now: float = 0.0, pos=(0.0, 0.0, 0.0), armed=True, altitude_ok=True) -> TickInputs:
    return TickInputs(now=now, pos_enu=pos, controller_armed=armed, altitude_ok=altitude_ok)


def test_wait_to_follow_path() -> None:
    mission = _demo_mission()
    ctx = MissionContext()
    out = tick(ctx, mission, _inputs(pos=(0, 0, 0), armed=True, altitude_ok=True))
    assert out.phase == PHASE_FOLLOW_PATH


def test_stay_in_wait_when_not_armed() -> None:
    mission = _demo_mission()
    ctx = MissionContext()
    out = tick(ctx, mission, _inputs(armed=False, altitude_ok=True))
    assert out.phase == "wait_arm_altitude"


def test_done_after_last_waypoint_hold() -> None:
    mission = build_mission_profile(
        (EnuPoint(1.0, 0.0, 3.0),),
        MissionProfileParams(hold_s=0.0),
    )
    ctx = MissionContext(phase=PHASE_FOLLOW_PATH, waypoint_index=0)
    # First tick — reaches waypoint, starts hold.
    tick(ctx, mission, _inputs(now=0.0, pos=(1.0, 0.0, 3.0)))
    # Second tick — hold elapsed (hold_s=0.0), advances and transitions to DONE.
    out = tick(ctx, mission, _inputs(now=0.1, pos=(1.0, 0.0, 3.0)))
    assert out.phase == PHASE_DONE
