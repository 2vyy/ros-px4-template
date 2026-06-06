"""Unit tests for the logfmt arc summary."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

from log_summary import build_run_summary, parse_logfmt  # noqa: E402


def test_parse_logfmt_basic() -> None:
    rec = parse_logfmt('t=2.50 src=mission level=info event=PHASE_CHANGE phase=hover')
    assert rec == {
        "t": 2.5,
        "src": "mission",
        "level": "info",
        "event": "PHASE_CHANGE",
        "phase": "hover",
    }


def test_parse_logfmt_quoted_value() -> None:
    rec = parse_logfmt('t=1.0 src=mission level=error msg="marker timeout"')
    assert rec["msg"] == "marker timeout"
    assert rec["level"] == "error"


def test_build_run_summary(tmp_path: Path) -> None:
    log = tmp_path / "latest.log"
    log.write_text(
        "\n".join(
            [
                "t=0.000 src=offboard level=info event=ARM_COMMAND_SENT attempt=1",
                "t=2.000 src=mission level=info event=PHASE_CHANGE phase=hover",
                't=10.000 src=mission level=error msg="marker timeout"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    summary = build_run_summary(log, run_id="test-run")
    assert summary["run_id"] == "test-run"
    assert summary["duration_s"] == 10.0
    assert summary["error_count"] == 1
    assert sorted(summary["nodes"]) == ["mission", "offboard"]
    assert len(summary["event_timeline"]) == 2
    assert summary["event_timeline"][0]["event"] == "ARM_COMMAND_SENT"
    assert summary["event_timeline"][0]["node"] == "offboard"
    assert summary["errors"][0]["msg"] == "marker timeout"


def test_build_run_summary_missing_file(tmp_path: Path) -> None:
    summary = build_run_summary(tmp_path / "nope.log", run_id="empty")
    assert summary["run_id"] == "empty"
    assert summary["duration_s"] == 0.0
    assert summary["event_timeline"] == []
