"""Unit tests for the importable per-run MCAP bag recorder (no ROS required)."""

from __future__ import annotations

import signal
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

import bag_recorder


def test_record_argv_builds_expected_command() -> None:
    run_dir = Path("/tmp/some-run")
    topics = ["/clock", "/fmu/out/vehicle_local_position_v1"]
    argv = bag_recorder._record_argv(run_dir, topics)

    assert argv[0] == "bash"
    assert argv[1] == "-lc"
    inner = argv[2]
    assert "ros2 bag record -s mcap -o" in inner
    assert "exec " in inner
    assert "source " in inner
    assert inner.rstrip().endswith("/clock /fmu/out/vehicle_local_position_v1")


def test_bag_topics_includes_skein_critical_channels() -> None:
    assert "/clock" in bag_recorder._BAG_TOPICS
    assert "/fmu/out/vehicle_local_position_v1" in bag_recorder._BAG_TOPICS


def test_start_writes_pidfile_and_passes_preexec_fn(monkeypatch, tmp_path) -> None:
    pidfile = tmp_path / "bag.pid"
    monkeypatch.setattr(bag_recorder, "BAG_PIDFILE", pidfile)
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    captured: dict = {}

    class FakeProc:
        pid = 4242

    def fake_spawn(argv, **kwargs):
        captured["argv"] = argv
        captured["kwargs"] = kwargs
        return FakeProc()

    proc = bag_recorder.start(run_dir, {"PATH": "/usr/bin"}, spawn=fake_spawn)

    assert proc is not None
    assert proc.pid == 4242
    assert pidfile.read_text() == "4242"
    assert "preexec_fn" in captured["kwargs"]
    assert captured["kwargs"]["preexec_fn"] is not None


def test_start_returns_none_and_does_not_raise_when_spawn_fails(monkeypatch, tmp_path) -> None:
    pidfile = tmp_path / "bag.pid"
    monkeypatch.setattr(bag_recorder, "BAG_PIDFILE", pidfile)
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    def failing_spawn(argv, **kwargs):
        raise OSError("mcap storage plugin missing")

    result = bag_recorder.start(run_dir, {}, spawn=failing_spawn)

    assert result is None
    assert not pidfile.exists()


def test_stop_returns_true_immediately_when_no_pidfile(monkeypatch, tmp_path) -> None:
    pidfile = tmp_path / "bag.pid"
    monkeypatch.setattr(bag_recorder, "BAG_PIDFILE", pidfile)

    assert bag_recorder.stop() is True


def test_stop_sigints_and_returns_true_when_process_dies(monkeypatch, tmp_path) -> None:
    pidfile = tmp_path / "bag.pid"
    pidfile.write_text("777")
    monkeypatch.setattr(bag_recorder, "BAG_PIDFILE", pidfile)

    calls: list[tuple[int, int]] = []
    monkeypatch.setattr(bag_recorder, "_getpgid", lambda pid: 777)
    monkeypatch.setattr(bag_recorder, "_killpg", lambda pgid, sig: calls.append((pgid, sig)))
    monkeypatch.setattr(bag_recorder, "_alive", lambda pid: False)

    result = bag_recorder.stop(timeout=0.5)

    assert result is True
    assert calls == [(777, signal.SIGINT)]
    assert not pidfile.exists()


def test_stop_escalates_to_sigkill_when_process_never_dies(monkeypatch, tmp_path) -> None:
    pidfile = tmp_path / "bag.pid"
    pidfile.write_text("778")
    monkeypatch.setattr(bag_recorder, "BAG_PIDFILE", pidfile)

    calls: list[tuple[int, int]] = []
    monkeypatch.setattr(bag_recorder, "_getpgid", lambda pid: 778)
    monkeypatch.setattr(bag_recorder, "_killpg", lambda pgid, sig: calls.append((pgid, sig)))
    monkeypatch.setattr(bag_recorder, "_alive", lambda pid: True)

    result = bag_recorder.stop(timeout=0.2)

    assert result is False
    assert calls == [(778, signal.SIGINT), (778, signal.SIGKILL)]
    assert not pidfile.exists()
