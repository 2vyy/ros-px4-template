"""Unit tests for cursor-based log reads and the events filter."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

from log_view import filter_events, format_trailer, read_new, read_since, slice_by_t


def test_read_new_returns_appended_lines_then_resets_on_truncation(tmp_path: Path) -> None:
    log = tmp_path / "latest.log"
    log.write_text("a\nb\n")
    lines, offset = read_new(log, 0)
    assert lines == ["a", "b"]
    log.write_text("a\nb\nc\n")
    lines, offset = read_new(log, offset)
    assert lines == ["c"]
    log.write_text("new\n")  # new boot clobbered the log
    lines, offset = read_new(log, offset)
    assert lines == ["new"]
    assert offset == log.stat().st_size


def test_read_since_returns_only_new_lines(tmp_path: Path) -> None:
    log = tmp_path / "latest.log"
    cur = tmp_path / "cursor.json"
    log.write_text("a\nb\n")
    lines, _ = read_since(log, cur)
    assert lines == ["a", "b"]
    log.write_text("a\nb\nc\n")
    lines, _ = read_since(log, cur)
    assert lines == ["c"]


def test_read_since_resets_on_truncation(tmp_path: Path) -> None:
    log = tmp_path / "latest.log"
    cur = tmp_path / "cursor.json"
    log.write_text("old1\nold2\n")
    read_since(log, cur)
    log.write_text("new\n")  # new boot clobbered the log
    lines, _ = read_since(log, cur)
    assert lines == ["new"]


def test_read_since_empty_is_definitive(tmp_path: Path) -> None:
    log = tmp_path / "latest.log"
    cur = tmp_path / "cursor.json"
    log.write_text("x\n")
    read_since(log, cur)
    lines, stats = read_since(log, cur)
    assert lines == []
    assert stats["raw"] == 0


def test_read_since_missing_log_is_empty(tmp_path: Path) -> None:
    lines, stats = read_since(tmp_path / "latest.log", tmp_path / "cursor.json")
    assert lines == []
    assert stats == {"raw": 0, "errors": 0}


def test_read_since_counts_errors(tmp_path: Path) -> None:
    log = tmp_path / "latest.log"
    cur = tmp_path / "cursor.json"
    log.write_text("t=1.0 src=a chatter\nt=2.0 src=b level=error msg=bad\n")
    _, stats = read_since(log, cur)
    assert stats == {"raw": 2, "errors": 1}


def test_filter_events_keeps_events_and_errors() -> None:
    lines = [
        "t=1.0 src=px4 chatter",
        "t=2.0 src=mission_manager event=TRANSITION to=follow",
        "t=3.0 src=position_node level=error msg=bad",
    ]
    kept = filter_events(lines)
    assert len(kept) == 2
    assert "chatter" not in " ".join(kept)


def test_trailer_counts() -> None:
    s = format_trailer(shown=2, raw=3, errors=1)
    assert "2" in s
    assert "3" in s
    assert "--raw" in s


def test_slice_by_t() -> None:
    lines = ["t=1.0 a", "t=5.0 b", "t=9.0 c"]
    assert slice_by_t(lines, 4.0, 6.0) == ["t=5.0 b"]
