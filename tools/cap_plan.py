#!/usr/bin/env python3
"""Build-order frontier over the claims DAG.

The agent loop is: run ``just cap plan``, execute the first actionable line,
record a passing run, and repeat until ``LADDER COMPLETE`` exits zero.
"""

from __future__ import annotations

from cap_status import RungInfo, display


def topo_order(data: dict) -> list[str]:
    """Return dependencies first, preserving registry order among ties."""
    capabilities = data.get("capabilities", {})
    ordered: list[str] = []

    def visit(name: str) -> None:
        if name in ordered or name not in capabilities:
            return
        for dependency in capabilities[name].get("requires", []):
            visit(dependency)
        ordered.append(name)

    for name in capabilities:
        visit(name)
    return ordered


def next_action(name: str, entry: dict, info: RungInfo) -> str:
    """Return the next literal action for one incomplete claim."""
    if "scenario_file" not in entry:
        return "(composite: prove requires below)"
    stem = entry["scenario_file"].removesuffix(".py")
    if "scenario missing" in info.reason:
        return f"just scenario-new {stem}"
    if "mission sim failing" in info.reason or "mission missing" in info.reason:
        return f"just mission sim {entry.get('mission', '')}".strip()
    if info.rung == "declared":
        return f"fix artifacts for {name}: {info.reason}"
    return f"just scenario {stem}"


def _closure(data: dict, target: str) -> set[str]:
    capabilities = data.get("capabilities", {})
    closure: set[str] = set()

    def visit(name: str) -> None:
        if name in closure or name not in capabilities:
            return
        closure.add(name)
        for dependency in capabilities[name].get("requires", []):
            visit(dependency)

    visit(target)
    return closure


def format_plan(
    data: dict,
    infos: dict[str, RungInfo],
    target: str | None,
) -> tuple[str, bool]:
    """Format the incomplete frontier and whether the selected ladder is done."""
    capabilities = data.get("capabilities", {})
    scope = _closure(data, target) if target else set(capabilities)
    lines: list[str] = []
    for name in topo_order(data):
        if name not in scope:
            continue
        info = infos[name]
        if info.rung == "sim-flown":
            continue
        lines.append(
            f"{name:<22} {display(info):<34} {next_action(name, capabilities[name], info)}"
        )
    if not lines:
        suffix = f" for {target}" if target else ""
        return f"LADDER COMPLETE{suffix}: everything sim-flown and fresh", True
    return "\n".join(lines), False
