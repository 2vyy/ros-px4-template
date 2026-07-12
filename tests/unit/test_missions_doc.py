"""docs/MISSIONS.md Behaviors/Guards tables must cover the live registry (plan 060).

The JSON schema auto-includes a new behavior/guard, but the human-facing
contract tables in MISSIONS.md are hand-maintained -- so a new behavior could
ship documented only in the schema. These tests fail until the prose table
gains (or drops) the row, closing that drift the same way the schema test does.
"""

from __future__ import annotations

import re
from pathlib import Path

from ros_px4_template_core.lib import mission as _m  # noqa: F401  (registers all)
from ros_px4_template_core.lib.mission.registry import known_behaviors, known_guards

DOC = Path(__file__).resolve().parents[2] / "docs" / "MISSIONS.md"


def _table_names(text: str, heading: str) -> set[str]:
    section = text.split(f"## {heading}", 1)[1].split("\n## ", 1)[0]
    return set(re.findall(r"^\| `([a-z_]+)` \|", section, flags=re.M))


def test_every_behavior_documented() -> None:
    names = _table_names(DOC.read_text(encoding="utf-8"), "Behaviors")
    missing = known_behaviors() - names
    assert not missing, f"add a row to docs/MISSIONS.md Behaviors table for: {sorted(missing)}"


def test_every_guard_documented() -> None:
    names = _table_names(DOC.read_text(encoding="utf-8"), "Guards")
    missing = known_guards() - names
    assert not missing, f"add a row to docs/MISSIONS.md Guards table for: {sorted(missing)}"


def test_no_phantom_rows() -> None:
    text = DOC.read_text(encoding="utf-8")
    phantom = (_table_names(text, "Behaviors") - known_behaviors()) | (
        _table_names(text, "Guards") - known_guards()
    )
    assert not phantom, f"docs/MISSIONS.md documents names not in the registry: {sorted(phantom)}"
