#!/usr/bin/env python3
"""Merge per-node JSONL logs, deduplicate repeats, write run summary for agents."""

from __future__ import annotations

import json
from pathlib import Path

import typer

from log_processing import build_run_summary, format_tabular, load_records, suppress_high_frequency

app = typer.Typer()


def run_merge(
    log_dir: Path,
    output_log: Path,
    output_jsonl: Path,
    summary: Path,
    run_id: str | None = None,
    no_dedup: bool = False,
    collapse_min: int = 4,
) -> None:
    """Core merge logic — callable programmatically without typer."""
    records = load_records(log_dir)
    raw_count = len(records)

    if not no_dedup:
        records = suppress_high_frequency(records)

    output_log.parent.mkdir(parents=True, exist_ok=True)
    with output_log.open("w", encoding="utf-8") as handle:
        for line in format_tabular(records):
            handle.write(line + "\n")

    output_jsonl.parent.mkdir(parents=True, exist_ok=True)
    with output_jsonl.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record) + "\n")

    summary_data = build_run_summary(records, log_dir=log_dir, run_id=run_id)
    summary.parent.mkdir(parents=True, exist_ok=True)
    summary.write_text(json.dumps(summary_data, indent=2) + "\n", encoding="utf-8")

    typer.echo(
        f"Merged {raw_count} raw -> {len(records)} lines\n"
        f"Logs -> {output_log} | {output_jsonl}\n"
        f"Summary -> {summary} ({summary_data['error_count']} errors, "
        f"{len(summary_data['event_timeline'])} timeline entries)"
    )


@app.command()
def main(
    log_dir: Path = typer.Option(Path("./logs"), "--log-dir"),
    output_log: Path = typer.Option(Path("./logs/merged.log"), "--output-log"),
    output_jsonl: Path = typer.Option(Path("./logs/merged.jsonl"), "--output-jsonl"),
    summary: Path = typer.Option(Path("./logs/run_summary.json"), "--summary"),
    run_id: str | None = typer.Option(None, "--run-id"),
    no_dedup: bool = typer.Option(False, "--no-dedup", help="Keep all raw lines in merged output"),
    collapse_min: int = typer.Option(4, "--collapse-min", help="Min repeats to collapse"),
) -> None:
    run_merge(
        log_dir=log_dir,
        output_log=output_log,
        output_jsonl=output_jsonl,
        summary=summary,
        run_id=run_id,
        no_dedup=no_dedup,
        collapse_min=collapse_min,
    )


if __name__ == "__main__":
    app()
