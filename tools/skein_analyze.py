#!/usr/bin/env python3
"""Helpers to run skein over a recorded run's artifacts (bag + ULog).

skein is a SEPARATE uv project (ROS-free); we invoke it as a subprocess via
`uv run --project <skein_dir> skein …` rather than importing it, to keep the
template's ROS-coupled env and skein's analysis env apart. These helpers build
the argv and resolve paths; tasks.py runs them.
"""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUNS_DIR = ROOT / "logs" / "runs"


class AnalyzeError(Exception):
    """A user-facing problem (missing run/artifact/skein dir). tasks.py maps this
    to a USAGE exit with the message."""


def resolve_skein_dir(skein_dir: str | None = None) -> Path:
    """The skein project dir: explicit arg, else $SKEIN_DIR, else the sibling
    ../skein next to this template. Must contain a pyproject.toml."""
    raw = skein_dir or os.environ.get("SKEIN_DIR", "").strip()
    path = Path(raw) if raw else ROOT.parent / "skein"
    if not (path / "pyproject.toml").is_file():
        raise AnalyzeError(
            f"skein project not found at {path} "
            "(set SKEIN_DIR or place skein beside this repo)."
        )
    return path


def resolve_run_dir(run: str, *, runs_dir: Path | None = None) -> Path:
    """Resolve 'latest' (the logs/runs/latest symlink) or a run id to its dir."""
    base = runs_dir or RUNS_DIR
    run_dir = base / run
    resolved = run_dir.resolve() if run_dir.is_symlink() else run_dir
    if not resolved.is_dir():
        raise AnalyzeError(
            f"no run at {run_dir} — record one with `just sim` first "
            "(runs live under logs/runs/<id>/)."
        )
    return resolved


def find_bag_mcap(run_dir: Path) -> Path | None:
    """The single *.mcap inside the run's ros2 bag dir (logs/runs/<id>/bag/), or
    None if absent."""
    bag_dir = run_dir / "bag"
    if not bag_dir.is_dir():
        return None
    mcaps = sorted(bag_dir.glob("*.mcap"))
    return mcaps[0] if mcaps else None


def overlay_argv(skein_dir: Path, *, bag: Path | None, ulog: Path | None, out: Path) -> list[str]:
    argv = ["uv", "run", "--project", str(skein_dir), "skein", "overlay", "--out", str(out)]
    if bag is not None:
        argv += ["--bag", str(bag)]
    if ulog is not None:
        argv += ["--ulog", str(ulog)]
    return argv


def query_argv(
    skein_dir: Path,
    artifact: Path,
    *,
    channel: str | None = None,
    where: str | None = None,
    stats: bool = False,
) -> list[str]:
    argv = ["uv", "run", "--project", str(skein_dir), "skein", "query", str(artifact)]
    if channel:
        argv += ["-c", channel]
    if where:
        argv += ["--where", where]
    if stats:
        argv += ["--stats"]
    return argv
