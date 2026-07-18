"""Unit tests for the run supervisor: heartbeat, run records, bounded supervise."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

from run_supervisor import (
    derive_heartbeat,
    format_heartbeat,
    list_run_records,
    parse_heartbeat,
    supervise,
    write_run_record,
)

# ── heartbeat derivation ──────────────────────────────────────────────────────


def test_derive_heartbeat_from_log_lines() -> None:
    lines = [
        "t=10.0 src=mission_manager event=TRANSITION from=takeoff to=follow guard=armed",
        't=12.5 src=px4 text="some chatter"',
        "t=14.0 src=offboard_controller event=ARM_COMMAND_SENT",
    ]
    hb = derive_heartbeat(lines, wall_now=100.0, wall_last_event=97.0)
    assert hb["phase"] == "follow"
    assert hb["t"] == 14.0
    assert hb["last_event"] == "ARM_COMMAND_SENT"
    assert hb["last_event_age_s"] == 3.0


def test_derive_heartbeat_empty() -> None:
    hb = derive_heartbeat([], wall_now=5.0, wall_last_event=None)
    assert hb["phase"] == "unknown"
    assert hb["last_event"] is None
    assert hb["last_event_age_s"] is None


def test_format_heartbeat_is_one_logfmt_line() -> None:
    line = format_heartbeat(
        {"t": 14.0, "phase": "follow", "last_event": "X", "last_event_age_s": 3.0}
    )
    assert "\n" not in line
    assert "phase=follow" in line


def test_parse_heartbeat_inverts_format() -> None:
    hb = {
        "t": 14.0,
        "phase": "follow",
        "last_event": "ARM_COMMAND_SENT",
        "last_event_age_s": 3.0,
        "scenario": "03_waypoint",
        "t_start": 2.5,
    }
    parsed = parse_heartbeat(format_heartbeat(hb) + "\n")
    assert parsed["phase"] == "follow"
    assert parsed["scenario"] == "03_waypoint"
    assert parsed["t"] == 14.0
    assert parsed["t_start"] == 2.5
    assert parsed["last_event_age_s"] == 3.0


def test_format_heartbeat_skips_none_values() -> None:
    line = format_heartbeat({"t": 0.0, "phase": "unknown", "last_event": None})
    assert "last_event" not in line


# ── run records ───────────────────────────────────────────────────────────────


def test_run_record_roundtrip_and_prune(tmp_path: Path) -> None:
    for i in range(55):
        write_run_record(tmp_path, f"s{i}", "PASS", None, 0.0, 1.0, "done", {}, keep=50)
    recs = list_run_records(tmp_path)
    assert len(recs) == 50
    assert recs[0]["name"] == "s54"  # newest first
    assert recs[0]["verdict"] == "PASS"


def test_run_record_fields_and_bag_dirs_untouched(tmp_path: Path) -> None:
    """Record files coexist with the bag-recording run DIRS in logs/runs/."""
    bag_dir = tmp_path / "20260718_120000"
    bag_dir.mkdir()
    path = write_run_record(
        tmp_path, "01_arm_takeoff", "STUCK", "stuck:log_silent", 2.0, 33.0, "takeoff", {"n": 1}
    )
    assert path.is_file()
    recs = list_run_records(tmp_path)
    assert recs[0] == {
        "name": "01_arm_takeoff",
        "verdict": "STUCK",
        "reason": "stuck:log_silent",
        "t_start": 2.0,
        "t_end": 33.0,
        "last_phase": "takeoff",
        "detail": {"n": 1},
        "recorded_at": recs[0]["recorded_at"],
        "record": path.stem,
    }
    assert bag_dir.is_dir()  # pruning never touches directories


def test_list_run_records_skips_unparseable(tmp_path: Path) -> None:
    write_run_record(tmp_path, "good", "PASS", None, 0.0, 1.0, "done", {})
    (tmp_path / "junk.json").write_text("{not json", encoding="utf-8")
    recs = list_run_records(tmp_path)
    assert [r["name"] for r in recs] == ["good"]


# ── supervise: bounded child execution ────────────────────────────────────────


def _paths(tmp_path: Path) -> dict:
    return {
        "heartbeat_path": tmp_path / "heartbeat",
        "pid_path": tmp_path / "run.pid",
    }


def test_supervise_clean_exit(tmp_path: Path) -> None:
    log = tmp_path / "latest.log"
    log.write_text("")
    rc, stuck = supervise(
        [sys.executable, "-c", "print('ok')"],
        "s",
        deadline_s=10,
        silence_s=10,
        log_path=log,
        cwd=tmp_path,
        poll_s=0.05,
        **_paths(tmp_path),
    )
    assert rc == 0
    assert stuck is None


def test_supervise_deadline_kills(tmp_path: Path) -> None:
    log = tmp_path / "latest.log"
    # keep the log growing so ONLY the deadline can fire
    child = (
        "import time, pathlib\n"
        "p = pathlib.Path('latest.log')\n"
        "for _ in range(200):\n"
        "    with p.open('a') as fh:\n"
        "        fh.write('t=1 src=x chatter\\n')\n"
        "    time.sleep(0.05)\n"
    )
    rc, stuck = supervise(
        [sys.executable, "-c", child],
        "s",
        deadline_s=0.5,
        silence_s=60,
        log_path=log,
        cwd=tmp_path,
        poll_s=0.05,
        **_paths(tmp_path),
    )
    assert rc is None
    assert stuck == "deadline_exceeded"


def test_supervise_silence_kills(tmp_path: Path) -> None:
    log = tmp_path / "latest.log"
    log.write_text("")
    rc, stuck = supervise(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        "s",
        deadline_s=60,
        silence_s=0.3,
        log_path=log,
        cwd=tmp_path,
        poll_s=0.05,
        **_paths(tmp_path),
    )
    assert rc is None
    assert stuck == "log_silent"


def test_supervise_writes_heartbeat_and_pid(tmp_path: Path) -> None:
    log = tmp_path / "latest.log"
    child = (
        "import time, pathlib\n"
        "pathlib.Path('latest.log').write_text("
        "'t=2.5 src=mm event=TRANSITION from=takeoff to=follow guard=g\\n')\n"
        "time.sleep(0.4)\n"
    )
    paths = _paths(tmp_path)
    rc, stuck = supervise(
        [sys.executable, "-c", child],
        "03_waypoint",
        deadline_s=10,
        silence_s=10,
        log_path=log,
        cwd=tmp_path,
        poll_s=0.05,
        **paths,
    )
    assert (rc, stuck) == (0, None)
    # heartbeat survives for post-mortem; pid file is cleaned up
    hb = parse_heartbeat(paths["heartbeat_path"].read_text(encoding="utf-8"))
    assert hb["scenario"] == "03_waypoint"
    assert hb["phase"] == "follow"
    assert hb["t_start"] == 2.5
    assert not paths["pid_path"].exists()
