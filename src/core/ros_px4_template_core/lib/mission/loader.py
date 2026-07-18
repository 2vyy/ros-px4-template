"""Load + validate a mission graph from a dict/YAML file."""

from __future__ import annotations

from pathlib import Path

import yaml

from ros_px4_template_core.lib.mission.behaviors import _split_waypoint_entry
from ros_px4_template_core.lib.mission.registry import known_behaviors, known_guards
from ros_px4_template_core.lib.mission.types import Inputs, Mission, StateDef, TransitionDef
from ros_px4_template_core.lib.waypoint_mission import load_path_yaml


class MissionError(ValueError):
    """Raised when a mission document is structurally invalid."""


def _resolve_waypoints(params: dict, base_dir: Path | None) -> dict:
    if "path_file" in params and "waypoints" not in params:
        p = Path(params["path_file"])
        if not p.is_absolute() and base_dir is not None:
            p = base_dir / p
        wps = load_path_yaml(p)
        params = dict(params)
        params["waypoints"] = [(w.x, w.y, w.z) for w in wps]
    if "waypoints" in params:
        # Fail a malformed inline waypoint at LOAD, not on every tick inside
        # follow_waypoints (the behavior's docstring promises load/first-tick).
        for i, entry in enumerate(params["waypoints"]):
            try:
                _split_waypoint_entry(tuple(entry), i)
            except (ValueError, TypeError) as e:
                raise MissionError(f"state waypoints: {e}") from e
    return params


def _neutral_inputs() -> Inputs:
    return Inputs(
        now=0.0,
        pose_enu=(0.0, 0.0, 0.0),
        yaw_enu=0.0,
        armed=False,
        altitude_ok=False,
        estimate_ok=True,
        detections=(),
        detection_stability={},
        input_ages={},
        battery_remaining=None,
        failsafe_active=False,
    )


def _probe_mission(states: dict[str, StateDef], edges: tuple[TransitionDef, ...]) -> None:
    """Evaluate every behavior and guard once against a neutral snapshot so
    param type/range errors surface at load, not mid-flight. Results are
    discarded; behaviors get a throwaway scratch dict.
    """
    from ros_px4_template_core.lib.mission.registry import get_behavior, get_guard

    inputs = _neutral_inputs()
    for name, sd in states.items():
        try:
            get_behavior(sd.behavior)({}, inputs, dict(sd.params))
        except MissionError:
            raise
        except Exception as e:
            raise MissionError(
                f"state '{name}': behavior '{sd.behavior}' params invalid: {e}"
            ) from e
    for t in edges:
        try:
            get_guard(t.guard)(inputs, {}, dict(t.params))
        except Exception as e:
            raise MissionError(
                f"transition to '{t.dst}': guard '{t.guard}' params invalid: {e}"
            ) from e


def load_mission_dict(doc: dict, base_dir: Path | None = None) -> Mission:
    requires_raw = doc.get("requires", [])
    if not (isinstance(requires_raw, list) and all(isinstance(r, str) for r in requires_raw)):
        raise MissionError("'requires' must be a list of claim-id strings")

    m = doc.get("mission")
    if not isinstance(m, dict):
        raise MissionError("missing top-level 'mission' mapping")

    behaviors = known_behaviors()
    guards = known_guards()

    states: dict[str, StateDef] = {}
    for name, sd in (m.get("states") or {}).items():
        bname = sd.get("behavior")
        if bname not in behaviors:
            raise MissionError(f"state '{name}': unknown behavior '{bname}'")
        params = _resolve_waypoints(dict(sd.get("params") or {}), base_dir)
        states[name] = StateDef(name, bname, params)

    def _edge(raw: dict, *, safety: bool) -> TransitionDef:
        gname = raw.get("guard")
        if gname not in guards:
            raise MissionError(f"transition: unknown guard '{gname}'")
        dst = raw.get("to")
        if dst not in states:
            raise MissionError(f"transition: unknown target '{dst}'")
        src = None if safety else raw.get("from")
        if not safety and src not in states:
            raise MissionError(f"transition: unknown source '{src}'")
        return TransitionDef(src, gname, dict(raw.get("params") or {}), dst)

    safety = tuple(_edge(r, safety=True) for r in (m.get("safety") or []))
    transitions = tuple(_edge(r, safety=False) for r in (m.get("transitions") or []))

    initial = m.get("initial")
    if initial not in states:
        raise MissionError(f"unknown initial state '{initial}'")
    terminal = frozenset(m.get("terminal") or [])
    for t in terminal:
        if t not in states:
            raise MissionError(f"unknown terminal state '{t}'")

    _probe_mission(states, safety + transitions)
    return Mission(initial, states, safety, transitions, terminal, tuple(requires_raw))


def load_mission_file(path: str | Path) -> Mission:
    p = Path(path).resolve()
    doc = yaml.safe_load(p.read_text(encoding="utf-8"))
    # path_file is documented as project-root-relative for the standard
    # config/missions/ layout (parents[2] == repo root). For missions loaded
    # from anywhere shallower/elsewhere, fall back to the mission file's own
    # directory rather than crashing.
    base_dir = p.parents[2] if len(p.parents) > 2 else p.parent
    return load_mission_dict(doc, base_dir=base_dir)
