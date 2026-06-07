"""Unit tests for the shared CLI verdict formatters and exit codes."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

from cli_verdict import (
    ExitCode,
    format_e2e_block,
    format_not_ready,
    format_ready,
    format_scenario,
    format_stopped,
)


def test_exit_codes_are_fixed() -> None:
    assert (ExitCode.OK, ExitCode.FAIL, ExitCode.USAGE, ExitCode.PRECONDITION) == (0, 1, 2, 3)


def test_format_ready_lists_checks() -> None:
    line = format_ready(["/fmu topics up", "rosbridge:9090", "GCS params committed"], 11.4)
    assert line.startswith("READY:")
    assert "/fmu topics up" in line
    assert "11.4s" in line
    assert "logs/latest.log" in line


def test_format_not_ready_names_reason() -> None:
    line = format_not_ready("gcs_heartbeat lost MAVLink", 180.0)
    assert line.startswith("NOT READY:")
    assert "gcs_heartbeat lost MAVLink" in line
    assert "180s" in line


def test_format_scenario_pass_and_fail() -> None:
    p = format_scenario("01_arm_takeoff", True, "armed in 3.1s, reached 2.5m", 6.2)
    f = format_scenario("03_waypoint", False, "timeout in PHASE_CLIMB (1/3)", 61.0)
    assert p.startswith("PASS 01_arm_takeoff")
    assert "6.2s" in p
    assert f.startswith("FAIL 03_waypoint")


def test_format_stopped_clean_vs_survivors() -> None:
    clean = format_stopped(["px4", "gz sim"], [])
    warn = format_stopped(["px4"], ["gzserver", "gzserver"])
    assert clean == "STOPPED: 2 processes killed, 0 survivors"
    assert warn.startswith("STOPPED WITH WARNINGS:")
    assert "gzserver" in warn
    # survivors are de-duplicated
    assert warn.count("gzserver") == 1


def test_format_e2e_block_counts_and_exit() -> None:
    block = format_e2e_block(
        [
            ("01_arm_takeoff", True, "armed, 2.5m", 6.2),
            ("03_waypoint", False, "timeout PHASE_CLIMB", 61.0),
        ]
    )
    assert "PASS 01_arm_takeoff" in block
    assert "FAIL 03_waypoint" in block
    assert "2 scenarios: 1 PASS, 1 FAIL  (exit 1)" in block


def test_format_e2e_block_all_pass_exit_0() -> None:
    block = format_e2e_block([("01", True, "ok", 1.0)])
    assert "1 scenarios: 1 PASS, 0 FAIL  (exit 0)" in block
