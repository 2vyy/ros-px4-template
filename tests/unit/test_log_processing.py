"""Unit tests for merge-time dedup and run summary."""

from __future__ import annotations

import json
from pathlib import Path

from log_processing import build_run_summary, collapse_repeats, load_records


def _rec(node: str, level: str, msg: str, ts: float, **extra: object) -> dict:
    return {"ts": ts, "ros_ts": ts, "node": node, "level": level, "msg": msg, **extra}


def test_collapse_repeats_merges_identical_run() -> None:
    records = [
        _rec("offboard_controller", "WARN", "Waiting for target_pose", float(i)) for i in range(10)
    ]
    out = collapse_repeats(records, min_count=4)
    assert len(out) == 1
    assert out[0]["count"] == 10
    assert out[0]["msg"] == "Waiting for target_pose"


def test_collapse_keeps_short_runs() -> None:
    records = [_rec("n", "INFO", "once", 1.0), _rec("n", "INFO", "once", 1.1)]
    out = collapse_repeats(records, min_count=4)
    assert len(out) == 2


def test_build_run_summary_timeline() -> None:
    records = [
        _rec("offboard_controller", "EVENT", "ARM_COMMAND_SENT", 100.0),
        _rec("mission_manager", "EVENT", "PHASE_CHANGE", 102.0, **{"from": "a", "to": "b"}),
        _rec("mission_manager", "ERROR", "Marker timeout", 110.0),
    ]
    summary = build_run_summary(records, log_dir=Path("."), run_id="test-run")
    assert summary["run_id"] == "test-run"
    assert summary["duration_s"] == 10.0
    assert summary["error_count"] == 1
    assert len(summary["event_timeline"]) == 3
    assert summary["errors"][0]["msg"] == "Marker timeout"


def test_load_records_skips_merged(tmp_path: Path) -> None:
    (tmp_path / "a.jsonl").write_text(
        json.dumps(_rec("n", "INFO", "hi", 1.0)) + chr(10),
        encoding="utf-8",
    )
    (tmp_path / "merged.jsonl").write_text("should skip" + chr(10), encoding="utf-8")
    loaded = load_records(tmp_path)
    assert len(loaded) == 1
