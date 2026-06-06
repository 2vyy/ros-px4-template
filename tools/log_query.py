#!/usr/bin/env python3
"""Agent-facing log subcommands: summarize and tail the session log."""

from __future__ import annotations

import subprocess
from pathlib import Path

import typer

app = typer.Typer()


@app.command()
def summary(
    log: Path = typer.Option(Path("./logs/latest.log"), "--log"),
    out: Path = typer.Option(Path("./logs/latest_summary.json"), "--out"),
    run_id: str | None = typer.Option(None, "--run-id"),
) -> None:
    """(Re)generate logs/latest_summary.json from logs/latest.log and print it."""
    from log_summary import main as summary_main

    summary_main(log=log, out=out, run_id=run_id)


@app.command()
def tail(log: Path = typer.Option(Path("./logs/latest.log"), "--log")) -> None:
    """Follow the live session log (logfmt is already readable)."""
    if not log.exists():
        log.parent.mkdir(parents=True, exist_ok=True)
        log.touch()
    subprocess.run(["tail", "-f", str(log)], check=False)


if __name__ == "__main__":
    app()
