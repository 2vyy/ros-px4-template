"""Load + validate a mission graph from a dict/YAML file."""

from __future__ import annotations

from pathlib import Path

import yaml

from ros_px4_template_core.lib.mission.behaviors import _split_waypoint_entry
from ros_px4_template_core.lib.mission.registry import known_behaviors, known_guards
from ros_px4_template_core.lib.mission.types import Mission, StateDef, TransitionDef
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


def load_mission_dict(doc: dict, base_dir: Path | None = None) -> Mission:
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

    return Mission(initial, states, safety, transitions, terminal)


def load_mission_file(path: str | Path) -> Mission:
    p = Path(path)
    doc = yaml.safe_load(p.read_text(encoding="utf-8"))
    return load_mission_dict(doc, base_dir=p.resolve().parents[2])
