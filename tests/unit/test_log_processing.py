"""Unit tests for merge-time dedup and run summary."""

from __future__ import annotations

import json
from pathlib import Path

from log_processing import build_run_summary, load_records, suppress_high_frequency


def _rec(node: str, level: str, msg: str, ts: float, **extra: object) -> dict:
    return {"ts": ts, "ros_ts": ts, "node": node, "level": level, "msg": msg, **extra}


def test_suppress_high_frequency_groups_by_node_msg() -> None:
    # 20 messages at 0.05s intervals (20Hz)
    records = [
        _rec("offboard_controller", "INFO", "Telemetry spam", float(i) * 0.05) for i in range(20)
    ]
    out = suppress_high_frequency(records, threshold_hz=10.0)
    # The first and last records are kept, others suppressed, plus a summary record added.
    # So we expect 3 records: first, last, and summary.
    assert len(out) == 3
    assert out[0]["ts"] == 0.0
    assert abs(out[1]["ts"] - 0.95) < 1e-6
    assert out[2]["is_summary"] is True
    assert "Summarized 20 msgs" in out[2]["msg"]


def test_suppress_high_frequency_keeps_low_frequency() -> None:
    # 5 messages at 1.0s intervals (1Hz)
    records = [_rec("offboard_controller", "INFO", "Sparse info", float(i) * 1.0) for i in range(5)]
    out = suppress_high_frequency(records, threshold_hz=10.0)
    assert len(out) == 5


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
    (tmp_path / "merged.log").write_text("should skip" + chr(10), encoding="utf-8")
    loaded = load_records(tmp_path)
    assert len(loaded) == 1
