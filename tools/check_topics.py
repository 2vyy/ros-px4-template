#!/usr/bin/env python3
"""Validate documented topics exist in a running ROS 2 graph."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import typer

app = typer.Typer()
TOPIC_RE = re.compile(r"`(/[a-zA-Z0-9_/]+)`")


@app.command()
def main(manifest: Path = typer.Option(Path("docs/TOPICS.md"), "--manifest")) -> None:
    text = manifest.read_text(encoding="utf-8")
    expected = sorted(set(TOPIC_RE.findall(text)))
    if not expected:
        typer.echo("No topics found in manifest", err=True)
        raise typer.Exit(1)

    result = subprocess.run(
        ["ros2", "topic", "list"],
        check=True,
        capture_output=True,
        text=True,
    )
    live = set(result.stdout.splitlines())
    missing = [t for t in expected if t not in live]
    for topic in expected:
        status = "OK" if topic in live else "MISSING"
        typer.echo(f"  [{status}] {topic}")
    if missing:
        typer.echo(f"{len(missing)} topic(s) missing", err=True)
        raise typer.Exit(1)
    typer.echo(f"All {len(expected)} documented topics are live.")


if __name__ == "__main__":
    app()
