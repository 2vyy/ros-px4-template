"""Unit tests for the logfmt arc summary."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

from log_summary import build_run_summary, format_failure_digest, parse_logfmt


def test_parse_logfmt_basic() -> None:
    rec = parse_logfmt("t=2.50 src=mission level=info event=PHASE_CHANGE phase=hover")
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


def test_digest_lists_errors_and_last_events(tmp_path: Path) -> None:
    log = tmp_path / "latest.log"
    lines = [
        't=1.000 src=mission level=error msg="first boom"',
        't=2.000 src=offboard level=error msg="second boom"',
    ]
    lines.extend(
        f"t={10 + idx:.3f} src=mission event=TRANSITION idx=e{idx:02d}" for idx in range(12)
    )
    log.write_text("\n".join(lines) + "\n", encoding="utf-8")

    digest = format_failure_digest(build_run_summary(log, run_id="digest-run"))

    assert "--- failure digest (logs/latest_summary.json) ---" in digest
    assert "run digest-run" in digest
    assert "first boom" in digest
    assert "second boom" in digest
    assert "idx=e00" not in digest
    assert "idx=e01" not in digest
    for idx in range(2, 12):
        assert f"idx=e{idx:02d}" in digest


def test_digest_empty_summary(tmp_path: Path) -> None:
    summary = build_run_summary(tmp_path / "missing.log", run_id="empty")

    digest = format_failure_digest(summary)

    assert "no errors or events captured (is logs/latest.log empty?)" in digest


def test_digest_caps_errors(tmp_path: Path) -> None:
    log = tmp_path / "latest.log"
    log.write_text(
        "\n".join(f't={idx:.3f} src=node level=error msg="boom-{idx}"' for idx in range(12)) + "\n",
        encoding="utf-8",
    )

    digest = format_failure_digest(build_run_summary(log, run_id="cap-run"))

    for idx in range(8):
        assert f"boom-{idx}" in digest
    for idx in range(8, 12):
        assert f"boom-{idx}" not in digest


def test_px4_arming_denied_captured(tmp_path: Path) -> None:
    log = tmp_path / "latest.log"
    log.write_text(
        "t=12.300 src=px4_sitl WARN [commander] Arming denied: Resolve system health failures\n",
        encoding="utf-8",
    )

    summary = build_run_summary(log, run_id="px4")

    assert summary["px4_events"] == [
        {
            "t": 12.3,
            "src": "px4_sitl",
            "tag": "ARMING_DENIED",
            "text": "WARN [commander] Arming denied: Resolve system health failures",
        }
    ]


def test_px4_failsafe_captured(tmp_path: Path) -> None:
    log = tmp_path / "latest.log"
    log.write_text("t=3.000 src=px4_sitl Failsafe activated: position lost\n", encoding="utf-8")

    summary = build_run_summary(log, run_id="px4")

    assert summary["px4_events"][0]["tag"] == "FAILSAFE"


def test_own_node_lines_not_px4_events(tmp_path: Path) -> None:
    log = tmp_path / "latest.log"
    log.write_text(
        "\n".join(
            [
                't=1.000 src=mission_manager level=error msg="Failsafe activated"',
                "t=2.000 src=mission_manager event=TRANSITION text=failsafe",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    summary = build_run_summary(log, run_id="own")

    assert summary["px4_events"] == []


def test_px4_events_in_digest(tmp_path: Path) -> None:
    log = tmp_path / "latest.log"
    log.write_text(
        "t=12.300 src=px4_sitl WARN [commander] Arming denied: Resolve system health failures\n",
        encoding="utf-8",
    )

    digest = format_failure_digest(build_run_summary(log, run_id="px4"))

    assert "px4:" in digest
    assert "t=12.3 [ARMING_DENIED] WARN [commander] Arming denied" in digest


def test_px4_events_cap(tmp_path: Path) -> None:
    log = tmp_path / "latest.log"
    log.write_text(
        "\n".join(f"t={idx:.3f} src=px4_sitl Failsafe activated: event {idx}" for idx in range(60))
        + "\n",
        encoding="utf-8",
    )

    summary = build_run_summary(log, run_id="px4")

    assert len(summary["px4_events"]) == 51
    assert summary["px4_events"][49]["tag"] == "FAILSAFE"
    assert summary["px4_events"][50]["tag"] == "TRUNCATED"
