#!/usr/bin/env python3
"""Manage tests/capabilities.toml capability registry."""

from __future__ import annotations

import tomllib
from datetime import date
from pathlib import Path

import tomli_w
import typer

app = typer.Typer()
REGISTRY = Path("tests/capabilities.toml")


def _load(registry: Path = REGISTRY) -> dict:
    if not registry.exists():
        return {"capabilities": {}}
    return tomllib.loads(registry.read_text(encoding="utf-8"))


def _save(data: dict, registry: Path = REGISTRY) -> None:
    registry.parent.mkdir(parents=True, exist_ok=True)
    registry.write_text(tomli_w.dumps(data), encoding="utf-8")


@app.command()
def show() -> None:
    data = _load()
    for name, cap in data.get("capabilities", {}).items():
        status = cap.get("status", "unknown")
        platforms = ", ".join(cap.get("platforms", []))
        typer.echo(f"{name}: {status} [{platforms}] — {cap.get('description', '')}")


@app.command()
def mark(capability: str, platform: str) -> None:
    data = _load()
    caps = data.setdefault("capabilities", {})
    entry = caps.setdefault(capability, {"description": "", "platforms": []})
    platforms = set(entry.get("platforms", []))
    platforms.add(platform)
    entry["platforms"] = sorted(platforms)
    entry["status"] = "verified"
    entry["last_verified"] = date.today().isoformat()
    _save(data)
    typer.echo(f"Marked {capability} verified on {platform}")


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

    Each entry is ``{"scenario": <stem>, "vision": <str>, "overlay": <str>}``.
    ``vision`` and ``overlay`` come from the ``sim_vision``/``sim_overlay`` fields
    in the registry, letting the e2e harness launch an isolated sim per config so
    hold scenarios and path scenarios don't share (and corrupt) one sim. Defaults
    keep older registries working: vision="none", overlay="auto_arm".
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
                }
            )
    return result


if __name__ == "__main__":
    app()
