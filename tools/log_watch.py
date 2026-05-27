#!/usr/bin/env python3
"""Follow live per-node JSONL logs and pretty-print new lines."""

from __future__ import annotations

import json
import time
from pathlib import Path

import typer

from log_pretty import print_record

app = typer.Typer()


@app.command()
def main(
    log_dir: Path = typer.Option(Path("./logs"), "--log-dir"),
    poll_s: float = typer.Option(0.25, "--poll-s"),
) -> None:
    offsets: dict[Path, int] = {}
    typer.echo(f"Watching {log_dir.resolve()} (*.jsonl, excluding merged.jsonl)")
    try:
        while True:
            for path in sorted(log_dir.glob("*.jsonl")):
                if path.name == "merged.jsonl":
                    continue
                if not path.exists():
                    continue
                size = path.stat().st_size
                start = offsets.get(path, 0)
                if size < start:
                    start = 0
                if size == start:
                    continue
                with path.open(encoding="utf-8") as handle:
                    handle.seek(start)
                    chunk = handle.read()
                    offsets[path] = handle.tell()
                for line in chunk.splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        print_record(json.loads(line))
                    except json.JSONDecodeError:
                        typer.echo(line)
            time.sleep(poll_s)
    except KeyboardInterrupt:
        typer.echo("Stopped.")


if __name__ == "__main__":
    app()
