"""Unit tests for the best-effort PX4 SITL ULog retrieval (no PX4 required)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

import ulog_retrieve


def _touch(path: Path, *, mtime: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"ulog-bytes")
    os.utime(path, (mtime, mtime))


def test_find_latest_ulog_returns_newest_at_or_after_since(tmp_path) -> None:
    log_root = tmp_path / "log"
    a = log_root / "2026-06-20" / "10_00_00.ulg"
    b = log_root / "2026-06-21" / "11_00_00.ulg"
    _touch(a, mtime=1000.0)
    _touch(b, mtime=2000.0)

    result = ulog_retrieve.find_latest_ulog(log_root, since_mtime=1500.0)

    assert result == b


def test_find_latest_ulog_returns_none_when_all_stale(tmp_path) -> None:
    log_root = tmp_path / "log"
    a = log_root / "2026-06-20" / "10_00_00.ulg"
    _touch(a, mtime=1000.0)

    result = ulog_retrieve.find_latest_ulog(log_root, since_mtime=1500.0)

    assert result is None


def test_retrieve_copies_fresh_ulog_to_session_ulg(tmp_path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    run_mtime = run_dir.stat().st_mtime

    px4_dir = tmp_path / "px4"
    log_root = px4_dir / "build" / "px4_sitl_default" / "rootfs" / "log"
    ulg = log_root / "2026-06-22" / "12_00_00.ulg"
    _touch(ulg, mtime=run_mtime + 10)

    dest = ulog_retrieve.retrieve(run_dir, px4_dir=str(px4_dir))

    assert dest == run_dir / "session.ulg"
    assert dest is not None
    assert dest.exists()
    assert dest.read_bytes() == ulg.read_bytes()


def test_retrieve_returns_none_when_no_fresh_ulog(tmp_path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    run_mtime = run_dir.stat().st_mtime

    px4_dir = tmp_path / "px4"
    log_root = px4_dir / "build" / "px4_sitl_default" / "rootfs" / "log"
    ulg = log_root / "2026-06-20" / "10_00_00.ulg"
    _touch(ulg, mtime=run_mtime - 100)

    dest = ulog_retrieve.retrieve(run_dir, px4_dir=str(px4_dir))

    assert dest is None
    assert not (run_dir / "session.ulg").exists()


def test_retrieve_returns_none_when_px4_log_root_missing(tmp_path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    dest = ulog_retrieve.retrieve(run_dir, px4_dir=str(tmp_path / "nope"))

    assert dest is None


def test_retrieve_never_raises_when_copy_fails(tmp_path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    run_mtime = run_dir.stat().st_mtime

    px4_dir = tmp_path / "px4"
    log_root = px4_dir / "build" / "px4_sitl_default" / "rootfs" / "log"
    ulg = log_root / "2026-06-22" / "12_00_00.ulg"
    _touch(ulg, mtime=run_mtime + 10)

    def failing_copy(src, dest):
        raise OSError("disk full")

    dest = ulog_retrieve.retrieve(run_dir, px4_dir=str(px4_dir), copy=failing_copy)

    assert dest is None
