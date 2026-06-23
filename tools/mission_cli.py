#!/usr/bin/env python3
"""`just mission` — list, validate, and describe mission YAML without a sim.

The mission loader (`lib/mission/loader.py`) fully validates a mission graph
(unknown behaviors/guards, bad initial/terminal/transition targets), but that
check only ran inside the `mission_manager` node at sim runtime. This sub-app
exposes the same loader from the CLI so a typo surfaces in under a second on a
bare checkout — no ROS, no colcon build, no Gazebo/PX4 boot.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import typer

# Make the rclpy-free mission library importable on a bare checkout (mirrors
# tests/conftest.py). Importing the loader runs the mission package __init__,
# which registers every behavior+guard; the loader needs no ROS or build.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "core"))

from ros_px4_template_core.lib.mission.loader import MissionError, load_mission_file
from ros_px4_template_core.lib.mission.registry import known_behaviors, known_guards
from ros_px4_template_core.lib.mission.types import Mission

_ROOT = Path(__file__).resolve().parents[1]
MISSIONS_DIR = _ROOT / "config" / "missions"

app = typer.Typer(help="List, validate, and describe mission YAML graphs (no sim needed).")


def mission_path(name: str) -> Path:
    """Resolve a mission reference to a file path.

    Accepts a bare name (``hover``), a filename (``hover.yaml``), or a direct
    path to a ``.yaml`` file. Bare names and filenames resolve under
    ``config/missions/``.
    """
    p = Path(name)
    if p.suffix == ".yaml" and p.exists():
        return p
    return MISSIONS_DIR / (name if name.endswith(".yaml") else f"{name}.yaml")


def list_missions() -> list[tuple[str, str]]:
    """Return ``[(name, first_comment_line)]`` for every config/missions/*.yaml."""
    out: list[tuple[str, str]] = []
    for f in sorted(MISSIONS_DIR.glob("*.yaml")):
        first = ""
        for line in f.read_text(encoding="utf-8").splitlines():
            if line.startswith("#"):
                first = line.lstrip("# ").rstrip()
                break
        out.append((f.stem, first))
    return out


def validate_mission(name: str) -> tuple[bool, str]:
    """Validate one mission. Never raises; returns ``(ok, message)``.

    ``message`` summarizes the graph when ok, or describes the failure when not.
    """
    path = mission_path(name)
    if not path.is_file():
        return (False, f"no such mission file: {path}")
    try:
        m = load_mission_file(path)
    except MissionError as e:
        return (False, f"invalid: {e}")
    except FileNotFoundError as e:  # a path_file referenced by the mission is missing
        return (False, f"missing referenced file: {e}")
    except Exception as e:  # malformed YAML, bad types
        return (False, f"{type(e).__name__}: {e}")
    return (True, f"{len(m.states)} states, initial={m.initial}, terminal={sorted(m.terminal)}")


def describe_mission(m: Mission) -> str:
    """Return a multi-line human summary of a loaded mission."""
    lines: list[str] = [f"initial: {m.initial}", "states:"]
    for name, sd in m.states.items():
        term = " (terminal)" if name in m.terminal else ""
        params = f" {sd.params}" if sd.params else ""
        lines.append(f"  {name}: {sd.behavior}{params}{term}")
    if m.safety:
        lines.append("safety (any state):")
        for t in m.safety:
            lines.append(f"  -[{t.guard}]-> {t.dst}")
    if m.transitions:
        lines.append("transitions:")
        for t in m.transitions:
            lines.append(f"  {t.src} -[{t.guard}]-> {t.dst}")
    lines.append(f"terminal: {sorted(m.terminal)}")
    return "\n".join(lines)


def build_schema() -> dict:
    """Build a draft 2020-12 JSON Schema for a mission document.

    The ``behavior`` and ``guard`` enums are generated from the live registry
    (`known_behaviors()` / `known_guards()`), not hardcoded, so the schema never
    drifts from the code. The structure mirrors `docs/MISSIONS.md`.
    """
    behaviors = sorted(known_behaviors())
    guards = sorted(known_guards())
    state_def = {
        "type": "object",
        "required": ["behavior"],
        "additionalProperties": False,
        "properties": {
            "behavior": {"enum": behaviors},
            "params": {"type": "object"},
        },
    }
    safety_edge = {
        "type": "object",
        "required": ["guard", "to"],
        "additionalProperties": False,
        "properties": {
            "guard": {"enum": guards},
            "params": {"type": "object"},
            "to": {"type": "string"},
        },
    }
    transition_edge = {
        "type": "object",
        "required": ["from", "guard", "to"],
        "additionalProperties": False,
        "properties": {
            "from": {"type": "string"},
            "guard": {"enum": guards},
            "params": {"type": "object"},
            "to": {"type": "string"},
        },
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "ros-px4-template mission",
        "type": "object",
        "required": ["mission"],
        "additionalProperties": False,
        "properties": {
            "mission": {
                "type": "object",
                "required": ["initial", "states"],
                "additionalProperties": False,
                "properties": {
                    "initial": {"type": "string"},
                    "states": {
                        "type": "object",
                        "minProperties": 1,
                        "additionalProperties": state_def,
                    },
                    "safety": {"type": "array", "items": safety_edge},
                    "transitions": {"type": "array", "items": transition_edge},
                    "terminal": {"type": "array", "items": {"type": "string"}},
                },
            }
        },
    }


@app.command("list")
def list_cmd() -> None:
    """List every mission in config/missions/ with its description."""
    for name, comment in list_missions():
        typer.echo(f"{name:24} {comment}")


@app.command("validate")
def validate_cmd(
    name: str = typer.Argument(..., help="Mission name (e.g. 'hover') or path to a .yaml"),
) -> None:
    """Validate a mission YAML without booting the sim (exit 0 ok, 2 invalid)."""
    ok, msg = validate_mission(name)
    if ok:
        typer.echo(f"OK {name}: {msg}")
        raise typer.Exit(0)
    typer.echo(f"FAIL {name}: {msg}", err=True)
    raise typer.Exit(2)  # ExitCode.USAGE — bad input


@app.command("show")
def show_cmd(
    name: str = typer.Argument(..., help="Mission name (e.g. 'hover') or path to a .yaml"),
) -> None:
    """Print a mission's states, transitions, and terminal set."""
    path = mission_path(name)
    if not path.is_file():
        typer.echo(f"no such mission file: {path}", err=True)
        raise typer.Exit(2)
    try:
        m = load_mission_file(path)
    except Exception as e:  # surface any load error to the CLI user
        typer.echo(f"cannot load {name}: {type(e).__name__}: {e}", err=True)
        raise typer.Exit(2) from None
    typer.echo(describe_mission(m))


@app.command("schema")
def schema_cmd() -> None:
    """Print a JSON Schema for mission YAML (behavior/guard enums from the registry)."""
    typer.echo(json.dumps(build_schema(), indent=2))


if __name__ == "__main__":
    app()
