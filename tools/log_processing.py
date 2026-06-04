"""Merge-time log processing: dedup, run summary (agent entry point)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def format_tabular(records: list[dict[str, Any]]) -> list[str]:
    if not records:
        return []
    t0 = float(records[0].get("ts", 0))
    lines = []
    for r in records:
        t = float(r.get("ts", 0)) - t0
        node = r.get("node", "?")
        level = r.get("level", "INFO")
        msg = r.get("msg", "")
        count = r.get("count", 1)

        line = f"[{t:>7.2f}] {node} {level}: {msg}"
        if count > 1:
            line += f" (x{count})"
        lines.append(line)
    return lines


def load_records(log_dir: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for jsonl_file in sorted(log_dir.glob("*.jsonl")):
        if jsonl_file.name in ("merged.log", "merged.jsonl", "latest.log", "latest.jsonl"):
            continue
        with jsonl_file.open(encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    records.sort(
        key=lambda r: (float(r.get("ts", 0)), str(r.get("node", "")), int(r.get("seq", 0)))
    )
    return records


def _record_signature(record: dict[str, Any]) -> tuple[Any, ...]:
    return (record.get("node"), record.get("level"), record.get("msg"))


def _average_numeric_fields(run: list[dict[str, Any]], base: dict[str, Any]) -> dict[str, Any]:
    skip = {"ts", "ros_ts", "node", "level", "msg", "count", "t_first", "t_last"}
    out = dict(base)
    for key in run[0]:
        if key in skip:
            continue
        values = [r[key] for r in run if key in r and isinstance(r[key], (int, float))]
        if values and len(values) == len(run):
            out[key] = sum(values) / len(values)
    return out


def suppress_high_frequency(
    records: list[dict[str, Any]],
    *,
    threshold_hz: float = 10.0,
    gap_s: float = 1.0,
    overrides: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Dynamically suppress high-frequency telemetry while preserving state changes."""
    if not records:
        return []

    overrides = overrides or {}

    class Stream:
        def __init__(self, sig: tuple[Any, ...], t0: float):
            self.signature = sig
            self.records: list[int] = []
            self.t_first = t0
            self.t_last = t0
            self.levels: set[str] = set()
            self.count = 0

    active_streams: dict[tuple[Any, ...], Stream] = {}
    all_streams: list[Stream] = []

    for idx, r in enumerate(records):
        sig = _record_signature(r)
        t = float(r.get("ts", 0))

        stream = active_streams.get(sig)
        if stream and (t - stream.t_last) > gap_s:
            all_streams.append(stream)
            stream = None

        if not stream:
            stream = Stream(sig, t)
            active_streams[sig] = stream

        stream.records.append(idx)
        stream.t_last = t
        if "level" in r:
            stream.levels.add(r["level"])
        stream.count += 1

    for stream in active_streams.values():
        all_streams.append(stream)

    suppressed_indices: set[int] = set()
    summary_records: dict[int, dict[str, Any]] = {}

    for stream in all_streams:
        if stream.count <= 2:
            continue

        duration = stream.t_last - stream.t_first
        hz = stream.count / duration if duration > 0 else float(stream.count)

        node = str(stream.signature[0])
        action = overrides.get(node, "auto")

        if action == "never":
            continue

        if action == "always" or hz > threshold_hz:
            last_level = None
            for i, idx in enumerate(stream.records):
                r = records[idx]
                level = r.get("level")
                is_first = i == 0
                is_last = i == len(stream.records) - 1
                level_changed = level != last_level

                if is_first or is_last or level_changed:
                    pass  # Keep
                else:
                    suppressed_indices.add(idx)

                last_level = level

            last_idx = stream.records[-1]
            summary_records[last_idx] = {
                "ts": stream.t_last,
                "node": node,
                "level": "INFO",
                "msg": f"--- Summarized {stream.count} msgs @ {hz:.1f}Hz (span: {duration:.1f}s), levels: {','.join(stream.levels)} ---",
                "is_summary": True,
            }

    out: list[dict[str, Any]] = []
    for idx, r in enumerate(records):
        if idx not in suppressed_indices:
            out.append(r)
        if idx in summary_records:
            out.append(summary_records[idx])

    return out


def infer_run_id(log_dir: Path, records: list[dict[str, Any]]) -> str:
    if rid := os.environ.get("LOG_RUN_ID"):
        return rid
    sim_logs = sorted(log_dir.glob("sim_*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
    if sim_logs:
        return sim_logs[0].name.removeprefix("sim_").removesuffix(".log")
    if records:
        from datetime import UTC, datetime

        return datetime.fromtimestamp(float(records[0]["ts"]), tz=UTC).strftime("%Y%m%dT%H%M%S")
    return "unknown"


def build_run_summary(
    records: list[dict[str, Any]],
    *,
    log_dir: Path,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Pre-digested flight arc for agents — read this before merged.log."""
    if not records:
        return {
            "run_id": run_id or infer_run_id(log_dir, records),
            "duration_s": 0.0,
            "nodes": [],
            "error_count": 0,
            "warn_count": 0,
            "event_timeline": [],
            "errors": [],
        }

    t0 = float(records[0].get("ts", 0))
    t1 = float(records[-1].get("ts", 0))
    rid = run_id or infer_run_id(log_dir, records)

    nodes = sorted({str(r.get("node", "?")) for r in records})
    errors_raw = [r for r in records if r.get("level") == "ERROR"]
    warns = [r for r in records if r.get("level") == "WARN"]

    def rel_t(record: dict[str, Any]) -> float:
        return round(float(record.get("ts", 0)) - t0, 2)

    raw_timeline: list[dict[str, Any]] = []
    for r in records:
        level = r.get("level")
        if level == "EVENT":
            entry: dict[str, Any] = {
                "t": rel_t(r),
                "node": r.get("node"),
                "event": r.get("msg"),
            }
            for k, v in r.items():
                if k not in ("ts", "ros_ts", "node", "level", "msg", "count", "t_first", "t_last"):
                    entry[k] = v
            if r.get("count", 1) > 1:
                entry["count"] = r["count"]
            raw_timeline.append(entry)
        elif level == "ERROR":
            entry = {
                "t": rel_t(r),
                "node": r.get("node"),
                "event": "ERROR",
                "msg": r.get("msg"),
            }
            if r.get("count", 1) > 1:
                entry["count"] = r["count"]
            raw_timeline.append(entry)

    # Events that repeat 3+ times are collapsed to one summary entry (first occurrence,
    # count, t_last). Single or rare events are kept verbatim in order.
    # This keeps ARM retry storms as one line while preserving unique transitions.
    from collections import defaultdict as _dd

    _groups: dict[tuple[Any, Any], list[dict[str, Any]]] = _dd(list)
    for entry in raw_timeline:
        _groups[(entry.get("node"), entry.get("event"))].append(entry)

    _seen: set[tuple[Any, Any]] = set()
    event_timeline: list[dict[str, Any]] = []
    for entry in raw_timeline:
        key = (entry.get("node"), entry.get("event"))
        if key in _seen:
            continue
        group = _groups[key]
        if len(group) >= 3:
            summarized = dict(group[0])
            summarized["count"] = len(group)
            summarized["t_last"] = group[-1]["t"]
            event_timeline.append(summarized)
        else:
            for e in group:
                event_timeline.append(dict(e))
        _seen.add(key)

    errors: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for r in errors_raw:
        sig = (r.get("node"), r.get("msg"))
        if sig in seen:
            continue
        seen.add(sig)
        err: dict[str, Any] = {
            "t": rel_t(r),
            "node": r.get("node"),
            "msg": r.get("msg"),
        }
        if r.get("count", 1) > 1:
            err["count"] = r["count"]
        errors.append(err)

    return {
        "run_id": rid,
        "duration_s": round(t1 - t0, 2),
        "nodes": nodes,
        "error_count": len(errors_raw),
        "warn_count": len(warns),
        "event_timeline": event_timeline,
        "errors": errors,
    }
