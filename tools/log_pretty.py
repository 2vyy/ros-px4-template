#!/usr/bin/env python3
"""Pretty-print merged JSONL logs from stdin."""

from __future__ import annotations

import json
import sys

from rich.console import Console
from rich.text import Text

console = Console()


def print_record(record: dict) -> None:
    """Print one structured log record."""
    level = record.get("level", "INFO")
    style = {"ERROR": "bold red", "WARN": "yellow", "EVENT": "cyan"}.get(level, "white")
    node = record.get("node", "?")
    msg = record.get("msg", "")
    skip = {"ts", "ros_ts", "node", "level", "msg", "count", "t_first", "t_last"}
    extra = {k: v for k, v in record.items() if k not in skip}
    text = Text(f"[{node}] {msg}", style=style)
    count = int(record.get("count", 1))
    if count > 1:
        t0 = record.get("t_first", record.get("ts"))
        t1 = record.get("t_last", record.get("ts"))
        text.append(f" (x{count}, {t0:.1f}-{t1:.1f}s)", style="dim")
    if extra:
        text.append(f" {extra}", style="dim")
    console.print(text)


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            print_record(json.loads(line))
        except json.JSONDecodeError:
            console.print(line)


if __name__ == "__main__":
    main()
