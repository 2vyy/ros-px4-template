"""Unit tests for the generated mission JSON Schema."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

from ros_px4_template_core.lib.mission.registry import known_behaviors, known_guards

from mission_cli import build_schema

_ROOT = Path(__file__).resolve().parents[2]
_MISSIONS = _ROOT / "config" / "missions"
_SCHEMA_FILE = _ROOT / "schemas" / "mission.schema.json"


def test_enums_come_from_registry() -> None:
    schema = build_schema()
    state = schema["properties"]["mission"]["properties"]["states"]["additionalProperties"]
    edge = schema["properties"]["mission"]["properties"]["transitions"]["items"]
    assert state["properties"]["behavior"]["enum"] == sorted(known_behaviors())
    assert edge["properties"]["guard"]["enum"] == sorted(known_guards())


def test_every_real_mission_validates() -> None:
    validator = Draft202012Validator(build_schema())
    for f in sorted(_MISSIONS.glob("*.yaml")):
        doc = yaml.safe_load(f.read_text(encoding="utf-8"))
        errors = sorted(str(error) for error in validator.iter_errors(doc))
        assert not errors, f"{f.name}: {errors}"


def test_unknown_behavior_rejected() -> None:
    validator = Draft202012Validator(build_schema())
    doc = {"mission": {"initial": "s0", "states": {"s0": {"behavior": "__nope__"}}}}
    assert list(validator.iter_errors(doc))


def test_unknown_guard_rejected() -> None:
    validator = Draft202012Validator(build_schema())
    doc = {
        "mission": {
            "initial": "s0",
            "states": {"s0": {"behavior": "hold"}},
            "transitions": [{"from": "s0", "guard": "__nope__", "to": "s0"}],
        }
    }
    assert list(validator.iter_errors(doc))


def test_committed_schema_matches_generated() -> None:
    committed = json.loads(_SCHEMA_FILE.read_text(encoding="utf-8"))
    msg = "stale schemas/mission.schema.json; regenerate with 'just mission schema'"
    assert committed == build_schema(), msg
