#!/usr/bin/env python3
"""Manage tests/capabilities.toml capability registry."""

from __future__ import annotations

import tomllib
from pathlib import Path

import typer

app = typer.Typer()
REGISTRY = Path("tests/capabilities.toml")


def _load(registry: Path = REGISTRY) -> dict:
    if not registry.exists():
        return {"capabilities": {}}
    return tomllib.loads(registry.read_text(encoding="utf-8"))


@app.command()
def show() -> None:
    """Print each claim's derived rung. Rungs are never stored."""
    from cap_evidence import EVIDENCE_ROOT, load_records
    from cap_status import (
        derive_all,
        display,
        evidence_age,
        real_artifacts_ok,
        real_changed_since,
        real_mission_ok,
    )

    data = _load()
    capabilities = data.get("capabilities", {})
    records = {name: load_records(EVIDENCE_ROOT, name) for name in capabilities}
    infos = derive_all(
        data,
        records,
        real_changed_since,
        real_artifacts_ok,
        real_mission_ok,
    )
    flown = 0
    for name, info in infos.items():
        age = ""
        if info.evidence:
            age = (
                f"  evidence {evidence_age(info.evidence)} old @ {info.evidence.get('commit', '?')}"
            )
        note = f"  ({info.reason})" if info.reason and info.rung != "sim-flown" else ""
        typer.echo(f"{name:<22} {display(info):<32}{age}{note}")
        flown += info.rung == "sim-flown"
    typer.echo(f"CLAIMS: {flown}/{len(infos)} sim-flown (derived, not stored)")


def scenarios_for_platform(platform: str = "sim", registry: Path = REGISTRY) -> list[str]:
    """Return scenario names (without .py) for the given platform, in TOML order."""
    data = _load(registry)
    result = []
    for cap in data.get("capabilities", {}).values():
        if platform in cap.get("platforms", []) and cap.get("scenario_file"):
            result.append(cap["scenario_file"].removesuffix(".py"))
    return result


def scenario_sim_configs(platform: str = "sim", registry: Path = REGISTRY) -> list[dict]:
    """Return per-scenario sim configs for the platform, in TOML order.

    Each entry is ``{"scenario", "vision", "overlay", "model", "world"}``.
    The fields come from ``sim_vision``/``sim_overlay``/``sim_model``/``sim_world``
    in the registry, letting the e2e harness launch an isolated sim per config so
    hold scenarios and path scenarios don't share (and corrupt) one sim, and so a
    perception scenario can boot a camera model + marker world while the synthetic
    scenarios stay on the default model/world. Defaults keep older registries
    working: vision="none", overlay="auto_arm", model="x500", world="default".
    """
    data = _load(registry)
    result = []
    for cap in data.get("capabilities", {}).values():
        if platform in cap.get("platforms", []) and cap.get("scenario_file"):
            result.append(
                {
                    "scenario": cap["scenario_file"].removesuffix(".py"),
                    "vision": cap.get("sim_vision", "none"),
                    "overlay": cap.get("sim_overlay", "auto_arm"),
                    "model": cap.get("sim_model", "x500"),
                    "world": cap.get("sim_world", "default"),
                }
            )
    return result


if __name__ == "__main__":
    app()
