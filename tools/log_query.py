#!/usr/bin/env python3
"""Query toolkit for agent-friendly log introspection."""

from __future__ import annotations

from pathlib import Path

import typer

app = typer.Typer()


@app.command()
def merge(
    log_dir: Path = typer.Option(Path("./logs"), "--log-dir"),
    output_log: Path = typer.Option(Path("./logs/latest.log"), "--output-log"),
    output_jsonl: Path = typer.Option(Path("./logs/latest.jsonl"), "--output-jsonl"),
    summary: Path = typer.Option(Path("./logs/latest_summary.json"), "--summary"),
    run_id: str | None = typer.Option(None, "--run-id"),
    no_dedup: bool = typer.Option(False, "--no-dedup", help="Keep all raw lines in merged output"),
    collapse_min: int = typer.Option(4, "--collapse-min", help="Min repeats to collapse"),
):
    """Merge per-node JSONL logs, deduplicate repeats, write run summary."""
    from log_merger import main as merge_main

    merge_main(
        log_dir=log_dir,
        output_log=output_log,
        output_jsonl=output_jsonl,
        summary=summary,
        run_id=run_id,
        no_dedup=no_dedup,
        collapse_min=collapse_min,
    )


@app.command()
def tail(
    log_dir: Path = typer.Option(Path("./logs"), "--log-dir"),
    poll_s: float = typer.Option(0.25, "--poll-s"),
):
    """Follow live per-node JSONL logs and pretty-print new lines."""
    from log_watch import main as watch_main

    watch_main(log_dir=log_dir, poll_s=poll_s)


if __name__ == "__main__":
    app()
