#!/usr/bin/env python3
"""Query toolkit for agent-friendly log introspection."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer

app = typer.Typer()


def _check_auto_merge(log_dir: Path) -> None:
    merged_path = log_dir / "merged.jsonl"
    node_logs = [f for f in log_dir.glob("*.jsonl") if f.name not in ("merged.jsonl", "merged.log")]
    should_merge = not merged_path.exists()
    if not should_merge and node_logs:
        merged_mtime = merged_path.stat().st_mtime
        should_merge = any(f.stat().st_mtime > merged_mtime for f in node_logs)

    if should_merge and node_logs:
        from log_merger import run_merge

        try:
            run_merge(
                log_dir=log_dir,
                output_log=log_dir / "merged.log",
                output_jsonl=merged_path,
                summary=log_dir / "run_summary.json",
            )
        except Exception as e:
            typer.echo(f"Auto-merge failed: {e}", err=True)


def _load_merged_jsonl(log_dir: Path) -> list[dict[str, Any]]:
    _check_auto_merge(log_dir)
    merged_path = log_dir / "merged.jsonl"

    if not merged_path.exists():
        typer.echo(f"Error: {merged_path} not found. No logs available to query.", err=True)
        raise typer.Exit(1)

    records = []
    with merged_path.open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            records.append(json.loads(line))
    return records


@app.command()
def summary(log_dir: Path = typer.Option(Path("./logs"), "--log-dir")):
    """Shows run summary from run_summary.json and general stats."""
    _check_auto_merge(log_dir)
    summary_path = log_dir / "run_summary.json"
    if not summary_path.exists():
        typer.echo("run_summary.json missing. No logs available.", err=True)
        raise typer.Exit(1)

    data = json.loads(summary_path.read_text(encoding="utf-8"))

    typer.echo(f"=== Run Summary (ID: {data.get('run_id')}) ===")
    typer.echo(f"Duration: {data.get('duration_s')}s")
    typer.echo(f"Nodes Active: {', '.join(data.get('nodes', []))}")
    typer.echo(f"Errors: {data.get('error_count')} | Warnings: {data.get('warn_count')}")

    if data.get("errors"):
        typer.echo("\n--- Error Fingerprints ---")
        for err in data["errors"]:
            count_str = f" (x{err['count']})" if err.get("count", 1) > 1 else ""
            typer.echo(f"[{err['t']:>7.2f}] {err['node']}: {err['msg']}{count_str}")

    if data.get("event_timeline"):
        typer.echo("\n--- Key Events Timeline ---")
        for ev in data["event_timeline"]:
            if ev.get("event") == "ERROR":
                continue
            count_str = f" (x{ev['count']})" if ev.get("count", 1) > 1 else ""
            typer.echo(f"[{ev['t']:>7.2f}] {ev['node']} -> {ev.get('event')}{count_str}")


@app.command()
def window(
    t: float = typer.Option(..., "--t", help="Target timestamp (relative to t0)"),
    window_s: float = typer.Option(5.0, "--window", help="Window in seconds (± around t)"),
    log_dir: Path = typer.Option(Path("./logs"), "--log-dir"),
):
    """Fetches a slice of logs around a specific relative timestamp."""
    records = _load_merged_jsonl(log_dir)
    if not records:
        return

    t0 = float(records[0].get("ts", 0))
    t_min = t - window_s
    t_max = t + window_s

    typer.echo(f"=== Window: [{t_min:.2f}s, {t_max:.2f}s] ===")
    for r in records:
        rel_t = float(r.get("ts", 0)) - t0
        if t_min <= rel_t <= t_max:
            node = r.get("node", "?")
            level = r.get("level", "INFO")
            msg = r.get("msg", "")
            if r.get("is_summary"):
                typer.echo(f"[{rel_t:>7.2f}] {node} {level}: {msg}")
            else:
                count = r.get("count", 1)
                count_str = f" (x{count})" if count > 1 else ""
                typer.echo(f"[{rel_t:>7.2f}] {node} {level}: {msg}{count_str}")


@app.command()
def merge(
    log_dir: Path = typer.Option(Path("./logs"), "--log-dir"),
    output_log: Path = typer.Option(Path("./logs/merged.log"), "--output-log"),
    output_jsonl: Path = typer.Option(Path("./logs/merged.jsonl"), "--output-jsonl"),
    summary: Path = typer.Option(Path("./logs/run_summary.json"), "--summary"),
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


@app.command()
def node(
    node_name: str,
    lines: int = typer.Option(50, "--lines", help="Number of lines to tail"),
    log_dir: Path = typer.Option(Path("./logs"), "--log-dir"),
):
    """Tail the last N lines of a specific node's JSONL log."""
    f = log_dir / f"{node_name}.jsonl"
    if not f.exists():
        available = [
            p.stem for p in log_dir.glob("*.jsonl") if p.name not in ("merged.jsonl", "merged.log")
        ]
        typer.echo(
            json.dumps({"error": f"no log for node '{node_name}'", "available": available}),
            err=True,
        )
        raise typer.Exit(1)

    try:
        with f.open("r", encoding="utf-8") as file:
            content = file.readlines()
        for line in content[-lines:]:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
                print(
                    json.dumps({k: v for k, v in r.items() if k != "ros_ts"}, separators=(",", ":"))
                )
            except json.JSONDecodeError:
                print(line)
    except Exception as e:
        typer.echo(f"Error reading node log: {e}", err=True)
        raise typer.Exit(1) from None


if __name__ == "__main__":
    app()
