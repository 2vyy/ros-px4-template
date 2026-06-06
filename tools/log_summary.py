#!/usr/bin/env python3
"""Build the pre-digested flight arc from logs/latest.log (agent entry point).

Reads the logfmt session log and emits run_id, duration, nodes, error/warn counts,
an event timeline, and a deduped error list. This is the one synthesis ripgrep
cannot do; everything else is grep on latest.log.
"""

from __future__ import annotations

import json
import os
import shlex
from pathlib import Path
from typing import Any

import typer

app = typer.Typer()

_RESERVED = {"t", "src", "level"}


def parse_logfmt(line: str) -> dict[str, Any]:
    """Parse one logfmt line into a dict. Coerces ``t`` to float."""
    rec: dict[str, Any] = {}
    for tok in shlex.split(line):
        if "=" not in tok:
            continue
        key, _, val = tok.partition("=")
        rec[key] = val
    if "t" in rec:
        try:
            rec["t"] = float(rec["t"])
        except ValueError:
            rec["t"] = 0.0
    return rec


def _infer_run_id(log_dir: Path) -> str:
    if rid := os.environ.get("LOG_RUN_ID"):
        return rid
    sims = sorted(log_dir.glob("sim_*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
    if sims:
        return sims[0].name.removeprefix("sim_").removesuffix(".log")
    return "unknown"


def build_run_summary(log_path: Path, *, run_id: str | None = None) -> dict[str, Any]:
    run_id = run_id or _infer_run_id(log_path.parent)
    if not log_path.exists():
        return {
            "run_id": run_id,
            "duration_s": 0.0,
            "nodes": [],
            "error_count": 0,
            "warn_count": 0,
            "event_timeline": [],
            "errors": [],
        }

    records = [
        parse_logfmt(line)
        for line in log_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    nodes = sorted({str(r.get("src", "?")) for r in records})
    times = [float(r.get("t", 0.0)) for r in records]
    duration = round(max(times) - min(times), 2) if times else 0.0

    timeline: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    error_count = warn_count = 0
    seen_err: set[tuple[Any, Any]] = set()
    for r in records:
        level = r.get("level")
        if level == "error":
            error_count += 1
            sig = (r.get("src"), r.get("msg"))
            if sig not in seen_err:
                seen_err.add(sig)
                errors.append({"t": r.get("t"), "node": r.get("src"), "msg": r.get("msg")})
        elif level == "warn":
            warn_count += 1
        if "event" in r:
            entry = {"t": r.get("t"), "node": r.get("src"), "event": r.get("event")}
            for k, v in r.items():
                if k not in _RESERVED and k != "event":
                    entry[k] = v
            timeline.append(entry)

    return {
        "run_id": run_id,
        "duration_s": duration,
        "nodes": nodes,
        "error_count": error_count,
        "warn_count": warn_count,
        "event_timeline": timeline,
        "errors": errors,
    }


@app.command()
def main(
    log: Path = typer.Option(Path("./logs/latest.log"), "--log"),
    out: Path = typer.Option(Path("./logs/latest_summary.json"), "--out"),
    run_id: str | None = typer.Option(None, "--run-id"),
) -> None:
    summary = build_run_summary(log, run_id=run_id)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    typer.echo(
        f"Summary -> {out} ({summary['error_count']} errors, "
        f"{len(summary['event_timeline'])} timeline entries)"
    )


if __name__ == "__main__":
    app()
