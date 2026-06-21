#!/usr/bin/env python3
"""Validate documented topics exist — live graph or source grep."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

import typer

app = typer.Typer()
TOPIC_RE = re.compile(r"`(/[a-zA-Z0-9_/]+)`")
_CELL_BACKTICK = re.compile(r"`([^`]+)`")
_VALID_DIRS = {"pub", "sub", "pub/sub"}


@dataclass(frozen=True)
class TopicSpec:
    name: str
    msg_type: str
    direction: str  # "pub" | "sub" | "pub/sub"
    conditional: bool = False  # True when Dir carries a "(vision)" marker


def parse_manifest(text: str) -> list[TopicSpec]:
    """Parse the 4-column Topics table rows into specs. Rows that are not a
    topic spec (headers, separators, the 2-column Subscriptions table) are
    skipped, so this is safe to run over the whole file."""
    specs: list[TopicSpec] = []
    for line in text.splitlines():
        s = line.strip()
        if not s.startswith("|"):
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if len(cells) != 4:
            continue
        name_m = _CELL_BACKTICK.search(cells[0])
        type_m = _CELL_BACKTICK.search(cells[1])
        dir_cell = cells[2].lower()
        conditional = "(vision)" in dir_cell
        direction = dir_cell.replace("(vision)", "").strip()
        if not name_m or not type_m or direction not in _VALID_DIRS:
            continue
        if not name_m.group(1).startswith("/"):
            continue
        specs.append(TopicSpec(name_m.group(1), type_m.group(1), direction, conditional))
    return specs


def should_enforce(spec: TopicSpec, vision: bool) -> bool:
    """A conditional (vision) topic is only enforced when vision is on."""
    return vision or not spec.conditional


def check_spec(spec: TopicSpec, observed_type: str | None, pub: int, sub: int) -> list[str]:
    """Pure verdict: return a list of problem strings ([] means OK)."""
    if observed_type is None:
        return ["not present on the live graph"]
    problems: list[str] = []
    if observed_type != spec.msg_type:
        problems.append(f"type {observed_type} != declared {spec.msg_type}")
    if "pub" in spec.direction and pub < 1:
        problems.append("declared pub but no publisher")
    if "sub" in spec.direction and sub < 1:
        problems.append("declared sub but no subscriber")
    return problems


def _live_topic_info(topic: str) -> tuple[str | None, int, int]:
    """(msg_type, publisher_count, subscription_count) from `ros2 topic info`."""
    result = subprocess.run(["ros2", "topic", "info", topic], capture_output=True, text=True)
    if result.returncode != 0:
        return None, 0, 0
    msg_type: str | None = None
    pub = sub = 0
    for raw in result.stdout.splitlines():
        ln = raw.strip()
        if ln.startswith("Type:"):
            msg_type = ln.split(":", 1)[1].strip()
        elif ln.startswith("Publisher count:"):
            pub = int(ln.split(":", 1)[1].strip() or 0)
        elif ln.startswith("Subscription count:"):
            sub = int(ln.split(":", 1)[1].strip() or 0)
    return msg_type, pub, sub


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
    vision: bool = typer.Option(
        False,
        "--vision",
        help="Enforce vision-conditional topics too (default: skip them)",
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

    specs = parse_manifest(text)
    failed_count = 0
    checked_count = 0
    for spec in specs:
        if not should_enforce(spec, vision):
            typer.echo(f"  [SKIP] {spec.name} (vision off)")
            continue
        checked_count += 1
        observed_type, pub, sub = _live_topic_info(spec.name)
        problems = check_spec(spec, observed_type, pub, sub)
        if problems:
            failed_count += 1
            typer.echo(f"  [FAIL] {spec.name}: {'; '.join(problems)}")
        else:
            typer.echo(f"  [OK] {spec.name}")
    if failed_count:
        typer.echo(f"{failed_count} topic(s) failed", err=True)
        raise typer.Exit(1)
    typer.echo(f"All {checked_count} checked topics match (type + direction).")


if __name__ == "__main__":
    app()
