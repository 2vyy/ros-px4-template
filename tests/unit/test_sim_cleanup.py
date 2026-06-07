"""Unit tests for the importable exhaustive teardown."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

import sim_cleanup


def test_scan_survivors_matches_patterns() -> None:
    # fake process table: (pid, command line)
    table = [
        (101, "/usr/bin/px4 -d etc"),
        (102, "ruby /opt/ros/gz sim server"),
        (103, "MicroXRCEAgent udp4 -p 8888"),
        (104, "/usr/bin/python3 unrelated_editor.py"),
    ]
    hits = sim_cleanup.scan_survivors(lister=lambda: table)
    pids = {pid for pid, _ in hits}
    assert pids == {101, 102, 103}  # the editor is not matched


def test_scan_never_kills_infrastructure_or_repo_path() -> None:
    # These all CONTAIN strings our stack uses (the repo path, "tests/scenarios/",
    # "px4"), but they are the distrobox/podman/terminal/agent processes. Killing
    # any of them ends the agent's own session. None may ever match.
    repo = "/home/ivy/Projects/ros-px4-template"
    table = [
        (201, f"distrobox enter ubuntu -- bash -lc cd {repo} && uv run"),
        (202, "/usr/bin/podman exec -it ubuntu bash -lc cd ros-px4-template && just stop"),
        (203, f"bash -lc cd {repo} && uv run python tests/scenarios/01.py"),
        (204, "conmon --syslog -c abcdef"),
        (205, "/usr/bin/foot"),
        (206, f"/usr/bin/python3 {repo}/tools/some_editor.py"),
    ]
    hits = sim_cleanup.scan_survivors(lister=lambda: table)
    assert hits == []


def test_match_label_distinguishes_target_from_wrapper() -> None:
    # The real scenario process (python interpreter, scenario path) IS a target;
    # the wrapper bash with the same path in its argv is NOT.
    node = "/x/install/ros_px4_template_core/lib/ros_px4_template_core/mission_manager"
    assert sim_cleanup._match_label("python3 /repo/tests/scenarios/01_arm.py") == "scenario"
    assert sim_cleanup._match_label("bash -lc uv run python tests/scenarios/01_arm.py") is None
    assert sim_cleanup._match_label(node) == "node"


def test_teardown_reports_clean_when_no_survivors(monkeypatch) -> None:
    # Nothing alive on the second scan -> clean result.
    monkeypatch.setattr(sim_cleanup, "_kill_pidfile_group", lambda: None)
    monkeypatch.setattr(sim_cleanup, "_sigkill", lambda pid: None)
    monkeypatch.setattr(sim_cleanup, "_stop_ros2_daemon", lambda: None)
    monkeypatch.setattr(sim_cleanup, "_clean_artifacts", lambda: None)

    scans = [
        [(101, "px4"), (102, "gz sim")],  # initial
        [],  # after kill
        [],  # final verify
    ]
    monkeypatch.setattr(sim_cleanup, "scan_survivors", lambda lister=None: scans.pop(0))

    result = sim_cleanup.teardown()
    assert sorted(result["killed"]) == ["gz", "px4"]
    assert result["survivors"] == []


def test_teardown_reports_survivors(monkeypatch) -> None:
    monkeypatch.setattr(sim_cleanup, "_kill_pidfile_group", lambda: None)
    monkeypatch.setattr(sim_cleanup, "_sigkill", lambda pid: None)
    monkeypatch.setattr(sim_cleanup, "_stop_ros2_daemon", lambda: None)
    monkeypatch.setattr(sim_cleanup, "_clean_artifacts", lambda: None)

    scans = [
        [(101, "px4"), (102, "gzserver")],  # initial
        [(102, "gzserver")],  # after kill: gzserver survives
        [(102, "gzserver")],  # final verify
    ]
    monkeypatch.setattr(sim_cleanup, "scan_survivors", lambda lister=None: scans.pop(0))

    result = sim_cleanup.teardown()
    assert result["survivors"] == ["gzserver"]
    assert "px4" in result["killed"]
