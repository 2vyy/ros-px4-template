"""Merge-time log processing: dedup, run summary (agent entry point)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def load_records(log_dir: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for jsonl_file in sorted(log_dir.glob("*.jsonl")):
        if jsonl_file.name == "merged.jsonl":
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
    records.sort(key=lambda r: float(r.get("ts", 0)))
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


def collapse_repeats(
    records: list[dict[str, Any]],
    *,
    min_count: int = 4,
    window_s: float | None = None,
) -> list[dict[str, Any]]:
    """Collapse consecutive identical (node, level, msg) runs into one record with count."""
    if not records:
        return []

    out: list[dict[str, Any]] = []
    i = 0
    while i < len(records):
        r = records[i]
        j = i + 1
        while j < len(records):
            nxt = records[j]
            if _record_signature(nxt) != _record_signature(r):
                break
            if window_s is not None:
                span = float(nxt.get("ts", 0)) - float(r.get("ts", 0))
                if span > window_s:
                    break
            j += 1
        count = j - i
        if count >= min_count:
            collapsed = dict(r)
            collapsed["count"] = count
            collapsed["t_first"] = float(r.get("ts", 0))
            collapsed["t_last"] = float(records[j - 1].get("ts", 0))
            collapsed["ts"] = collapsed["t_last"]
            collapsed = _average_numeric_fields(records[i:j], collapsed)
            out.append(collapsed)
        else:
            out.extend(records[i:j])
        i = j
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
    """Pre-digested flight arc for agents — read this before merged.jsonl."""
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

    event_timeline: list[dict[str, Any]] = []
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
            event_timeline.append(entry)
        elif level == "ERROR":
            entry = {
                "t": rel_t(r),
                "node": r.get("node"),
                "event": "ERROR",
                "msg": r.get("msg"),
            }
            if r.get("count", 1) > 1:
                entry["count"] = r["count"]
            event_timeline.append(entry)

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
