#!/usr/bin/env python3
"""Cursor-based incremental log reads: 'tail without the -f' for agents.

`read_since` returns only what appended to the log since the last call,
tracked by a JSON cursor file, so repeated calls are cheap and an empty
result is definitive ("nothing new"), never "try again". `filter_events`
reduces a window to state transitions and errors; `slice_by_t` cuts the
session log down to one run's [t_start, t_end] span.
"""

from __future__ import annotations

import json
from pathlib import Path

from log_summary import parse_logfmt


def _is_error(rec: dict) -> bool:
    return rec.get("level") == "error"


def read_new(log_path: Path, offset: int) -> tuple[list[str], int]:
    """Lines appended past ``offset``; new offset. Truncation resets to 0.

    Shared primitive: stat size, treat a log smaller than ``offset`` as a
    new boot (reset the cursor), read only the appended bytes otherwise.
    """
    size = log_path.stat().st_size if log_path.exists() else 0
    if size < offset:
        offset = 0
    lines: list[str] = []
    if size > offset:
        with log_path.open("r", encoding="utf-8", errors="replace") as fh:
            fh.seek(offset)
            lines = fh.read().splitlines()
    return lines, size


def read_since(log_path: Path, cursor_path: Path) -> tuple[list[str], dict]:
    """Return (new lines, {"raw": n, "errors": n}) since the cursor; advance it.

    Cursor file is JSON ``{"offset": int, "size": int}``. A log smaller on
    disk than the stored offset means a new boot clobbered it: reset to 0 so
    the whole new log is the delta.
    """
    offset = 0
    try:
        cur = json.loads(cursor_path.read_text(encoding="utf-8"))
        offset = int(cur.get("offset", 0))
    except (OSError, ValueError, TypeError):
        offset = 0
    lines, size = read_new(log_path, offset)
    cursor_path.write_text(json.dumps({"offset": size, "size": size}) + "\n", encoding="utf-8")
    errors = sum(1 for ln in lines if _is_error(parse_logfmt(ln)))
    return lines, {"raw": len(lines), "errors": errors}


def filter_events(lines: list[str]) -> list[str]:
    """Keep lines whose parsed record has an ``event=`` key or ``level=error``."""
    kept: list[str] = []
    for ln in lines:
        rec = parse_logfmt(ln)
        if "event" in rec or _is_error(rec):
            kept.append(ln)
    return kept


def format_trailer(*, shown: int, raw: int, errors: int) -> str:
    """Aggregate line printed after an events window."""
    return f"{shown} events shown ({raw} raw lines this window, {errors} errors); --raw for all"


def slice_by_t(lines: list[str], t0: float, t1: float) -> list[str]:
    """Lines whose ``t`` falls within [t0, t1]; lines without a ``t`` are dropped."""
    out: list[str] = []
    for ln in lines:
        t = parse_logfmt(ln).get("t")
        if isinstance(t, float) and t0 <= t <= t1:
            out.append(ln)
    return out
