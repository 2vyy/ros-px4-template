#!/usr/bin/env python3
"""Build the pre-digested flight arc from logs/latest.log (agent entry point).

Reads the logfmt session log and emits run_id, duration, nodes, error/warn counts,
an event timeline, and a deduped error list. This is the one synthesis ripgrep
cannot do; everything else is grep on latest.log.
"""

from __future__ import annotations

import json
import os
import shlex
from pathlib import Path
from typing import Any

import typer

app = typer.Typer()

_RESERVED = {"t", "src", "level"}
_PX4_EVENT_PATTERNS: tuple[tuple[str, str], ...] = (
    ("arming denied", "ARMING_DENIED"),
    ("disarmed by", "DISARMED"),
    ("failsafe", "FAILSAFE"),
    ("preflight fail", "PREFLIGHT_FAIL"),
    ("emergency", "EMERGENCY"),
    ("ekf2", "EKF"),
    ("mag sensors inconsistent", "SENSOR_INCONSISTENT"),
    ("accel sensors inconsistent", "SENSOR_INCONSISTENT"),
    ("rtl", "RTL"),
    ("land detected", "LAND_DETECTED"),
    ("takeoff detected", "TAKEOFF_DETECTED"),
)


def parse_logfmt(line: str) -> dict[str, Any]:
    """Parse one logfmt line into a dict. Coerces ``t`` to float."""
    rec: dict[str, Any] = {}
    try:
        tokens = shlex.split(line)
    except ValueError:
        tokens = line.split()
    extras: list[str] = []
    for tok in tokens:
        if "=" not in tok:
            extras.append(tok)
            continue
        key, _, val = tok.partition("=")
        rec[key] = val.strip('"')
    if extras:
        rec["text"] = " ".join(extras)
    if "t" in rec:
        try:
            rec["t"] = float(rec["t"])
        except ValueError:
            rec["t"] = 0.0
    return rec


def classify_px4_line(text: str) -> str | None:
    low = text.lower()
    for needle, tag in _PX4_EVENT_PATTERNS:
        if needle in low:
            return tag
    return None


def _infer_run_id(log_dir: Path) -> str:
    if rid := os.environ.get("LOG_RUN_ID"):
        return rid
    latest = log_dir / "latest.log"
    if latest.exists():
        from datetime import UTC, datetime

        return datetime.fromtimestamp(latest.stat().st_mtime, tz=UTC).strftime("%Y%m%dT%H%M%S")
    return "unknown"


def build_run_summary(log_path: Path, *, run_id: str | None = None) -> dict[str, Any]:
    run_id = run_id or _infer_run_id(log_path.parent)
    if not log_path.exists():
        return {
            "run_id": run_id,
            "duration_s": 0.0,
            "nodes": [],
            "error_count": 0,
            "warn_count": 0,
            "event_timeline": [],
            "errors": [],
            "px4_events": [],
        }

    records = [
        parse_logfmt(line)
        for line in log_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    nodes = sorted({str(r.get("src", "?")) for r in records})
    times = [float(r.get("t", 0.0)) for r in records]
    duration = round(max(times) - min(times), 2) if times else 0.0

    timeline: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    px4_events: list[dict[str, Any]] = []
    error_count = warn_count = 0
    seen_err: set[tuple[Any, Any]] = set()
    last_px4_sig: tuple[Any, str] | None = None
    for r in records:
        level = r.get("level")
        if level == "error":
            error_count += 1
            sig = (r.get("src"), r.get("msg"))
            if sig not in seen_err:
                seen_err.add(sig)
                errors.append({"t": r.get("t"), "node": r.get("src"), "msg": r.get("msg")})
        elif level == "warn":
            warn_count += 1
        if "event" in r:
            entry = {"t": r.get("t"), "node": r.get("src"), "event": r.get("event")}
            for k, v in r.items():
                if k not in _RESERVED and k != "event":
                    entry[k] = v
            timeline.append(entry)
        text = str(r.get("text", ""))
        if text and level is None and "event" not in r:
            tag = classify_px4_line(text)
            sig = (r.get("src"), text)
            if tag is not None and sig != last_px4_sig:
                if len(px4_events) >= 50:
                    px4_events.append(
                        {
                            "t": r.get("t"),
                            "src": r.get("src"),
                            "tag": "TRUNCATED",
                            "text": "px4_events truncated after 50 entries",
                        }
                    )
                    break
                px4_events.append(
                    {
                        "t": r.get("t"),
                        "src": r.get("src"),
                        "tag": tag,
                        "text": text[:160],
                    }
                )
            last_px4_sig = sig

    return {
        "run_id": run_id,
        "duration_s": duration,
        "nodes": nodes,
        "error_count": error_count,
        "warn_count": warn_count,
        "event_timeline": timeline,
        "errors": errors,
        "px4_events": px4_events,
    }


def format_failure_digest(
    summary: dict[str, Any], *, max_errors: int = 8, max_events: int = 10
) -> str:
    """Compact human/agent-readable digest of a failed run's summary."""
    lines = ["--- failure digest (logs/latest_summary.json) ---"]
    lines.append(
        f"run {summary.get('run_id', 'unknown')}, {summary.get('duration_s', 0.0)}s, "
        f"{summary.get('error_count', 0)} errors / {summary.get('warn_count', 0)} warnings"
    )
    errors = list(summary.get("errors", []))[:max_errors]
    px4_events = list(summary.get("px4_events", []))[:8]
    events = list(summary.get("event_timeline", []))[-max_events:]
    if errors:
        lines.append("errors:")
        for err in errors:
            lines.append(f"  t={err.get('t')} {err.get('node')}: {err.get('msg')}")
    if px4_events:
        lines.append("px4:")
        for event in px4_events:
            lines.append(f"  t={event.get('t')} [{event.get('tag')}] {event.get('text')}")
    if events:
        lines.append("last events:")
        for event in events:
            extras = " ".join(
                f"{k}={v}" for k, v in event.items() if k not in {"t", "node", "event"}
            )
            suffix = f" {extras}" if extras else ""
            lines.append(f"  t={event.get('t')} {event.get('node')} {event.get('event')}{suffix}")
    if not errors and not px4_events and not events:
        lines.append("no errors or events captured (is logs/latest.log empty?)")
    lines.append("full log: logs/latest.log | summary: just log summary")
    return "\n".join(lines)


@app.command()
def main(
    log: Path = typer.Option(Path("./logs/latest.log"), "--log"),
    out: Path = typer.Option(Path("./logs/latest_summary.json"), "--out"),
    run_id: str | None = typer.Option(None, "--run-id"),
) -> None:
    summary = build_run_summary(log, run_id=run_id)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    typer.echo(
        f"Summary -> {out} ({summary['error_count']} errors, "
        f"{len(summary['event_timeline'])} timeline entries)"
    )


if __name__ == "__main__":
    app()
