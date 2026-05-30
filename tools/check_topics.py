#!/usr/bin/env python3
"""Validate documented topics exist — live graph or source grep."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import typer

app = typer.Typer()
TOPIC_RE = re.compile(r"`(/[a-zA-Z0-9_/]+)`")


def _topics_in_source(topics: list[str], source_roots: list[Path]) -> set[str]:
    """Return the subset of topics found as substrings in .py files under source_roots."""
    found: set[str] = set()
    remaining = set(topics)
    for root in source_roots:
        if not root.is_dir():
            continue
        for py_file in root.rglob("*.py"):
            try:
                text = py_file.read_text(encoding="utf-8")
            except OSError:
                continue
            for topic in list(remaining):
                if topic in text:
                    found.add(topic)
                    remaining.discard(topic)
            if not remaining:
                return found
    return found


@app.command()
def main(
    manifest: Path = typer.Option(Path("docs/TOPICS.md"), "--manifest"),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Grep source files instead of querying live ros2 topic list"
    ),
    source_dir: Path = typer.Option(
        Path("."),
        "--source-dir",
        help="Root to search for .py files in dry-run mode (default: repo root)",
    ),
) -> None:
    text = manifest.read_text(encoding="utf-8")
    expected = sorted(set(TOPIC_RE.findall(text)))
    if not expected:
        typer.echo("No topics found in manifest", err=True)
        raise typer.Exit(1)

    if dry_run:
        roots = [source_dir / d for d in ("src", "sim", "hardware", "tools")]
        present = _topics_in_source(expected, roots)
        missing = [t for t in expected if t not in present]
        for topic in expected:
            status = "OK" if topic in present else "MISSING"
            typer.echo(f"  [{status}] {topic}")
        if missing:
            typer.echo(f"{len(missing)} topic(s) not found in source", err=True)
            raise typer.Exit(1)
        typer.echo(f"All {len(expected)} documented topics found in source.")
        return

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
