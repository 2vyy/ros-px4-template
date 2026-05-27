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


def _load() -> dict:
    if not REGISTRY.exists():
        return {"capabilities": {}}
    return tomllib.loads(REGISTRY.read_text(encoding="utf-8"))


def _save(data: dict) -> None:
    REGISTRY.parent.mkdir(parents=True, exist_ok=True)
    REGISTRY.write_text(tomli_w.dumps(data), encoding="utf-8")


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


if __name__ == "__main__":
    app()
