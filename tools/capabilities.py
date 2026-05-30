#!/usr/bin/env python3
"""Manage tests/capabilities.toml capability registry."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import typer

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib  # type: ignore[no-redef]

import tomli_w

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


def update_from_scenario(
    scenario_name: str, platform: str, passed: bool, registry: Path = REGISTRY
) -> bool:
    """Update capability registry for the capability matching scenario_name.

    Increments run_count every call; increments pass_count and updates
    last_verified only when passed=True. Returns True if a matching capability
    was found.
    """
    data = _load(registry)
    caps = data.get("capabilities", {})
    for cap in caps.values():
        if cap.get("scenario_file") == f"{scenario_name}.py" and platform in cap.get(
            "platforms", []
        ):
            cap["run_count"] = cap.get("run_count", 0) + 1
            if passed:
                cap["pass_count"] = cap.get("pass_count", 0) + 1
                cap["last_verified"] = date.today().isoformat()
                cap["status"] = "verified"
            _save(data, registry)
            return True
    return False


if __name__ == "__main__":
    app()
