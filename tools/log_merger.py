#!/usr/bin/env python3
"""Merge per-node JSONL logs, deduplicate repeats, write run summary for agents."""

from __future__ import annotations

import json
from pathlib import Path

import typer

from log_processing import build_run_summary, collapse_repeats, load_records

app = typer.Typer()


@app.command()
def main(
    log_dir: Path = typer.Option(Path("./logs"), "--log-dir"),
    output: Path = typer.Option(Path("./logs/merged.jsonl"), "--output"),
    summary: Path = typer.Option(Path("./logs/run_summary.json"), "--summary"),
    run_id: str | None = typer.Option(None, "--run-id"),
    no_dedup: bool = typer.Option(False, "--no-dedup", help="Keep all raw lines in merged output"),
    collapse_min: int = typer.Option(4, "--collapse-min", help="Min repeats to collapse"),
) -> None:
    records = load_records(log_dir)
    raw_count = len(records)

    if not no_dedup:
        records = collapse_repeats(records, min_count=collapse_min)

    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record) + "\n")

    summary_data = build_run_summary(records, log_dir=log_dir, run_id=run_id)
    summary.parent.mkdir(parents=True, exist_ok=True)
    summary.write_text(json.dumps(summary_data, indent=2) + "\n", encoding="utf-8")

    typer.echo(
        f"Merged {raw_count} raw -> {len(records)} lines -> {output}\n"
        f"Summary -> {summary} ({summary_data['error_count']} errors, "
        f"{len(summary_data['event_timeline'])} timeline entries)"
    )


if __name__ == "__main__":
    app()
