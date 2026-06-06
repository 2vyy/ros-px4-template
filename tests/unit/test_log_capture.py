"""Unit tests for the log_capture streaming filter."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

from log_capture import Capturer, split_prefix


def test_split_prefix_node() -> None:
    assert split_prefix("[offboard_controller-3] t=5 event=ARM") == (
        "offboard_controller",
        "t=5 event=ARM",
    )


def test_split_prefix_none() -> None:
    assert split_prefix("raw line no prefix") == (None, "raw line no prefix")


def _drive(lines: list[tuple[str, float]]) -> list[str]:
    cap = Capturer()
    out: list[str] = []
    for raw, now in lines:
        out.extend(cap.feed(raw, now))
    out.extend(cap.flush())
    return out


def test_relativizes_node_epoch_and_tags_src() -> None:
    out = _drive(
        [
            ("[mission-1] t=1000.000 level=info event=PHASE_CHANGE phase=hover", 9999.0),
            ("[px4-2] WARN ekf reset", 1002.5),
        ]
    )
    assert out[0] == "t=0.000 src=mission level=info event=PHASE_CHANGE phase=hover"
    # third-party line has no embedded t=; arrival time is used, relative to t0=1000
    assert out[1] == "t=2.500 src=px4 WARN ekf reset"


def test_consecutive_identical_collapse() -> None:
    out = _drive(
        [
            ("[offboard-1] t=1000.0 event=ARM_COMMAND_SENT", 1000.0),
            ("[offboard-1] t=1000.1 event=ARM_COMMAND_SENT", 1000.1),
            ("[offboard-1] t=1000.2 event=ARM_COMMAND_SENT", 1000.2),
            ("[offboard-1] t=1001.0 event=ARM_ACK_OK", 1001.0),
        ]
    )
    assert out[0] == "t=0.000 src=offboard event=ARM_COMMAND_SENT (x3)"
    assert out[1] == "t=1.000 src=offboard event=ARM_ACK_OK"


def test_no_prefix_line_is_kept_as_unknown() -> None:
    out = _drive([("plain gazebo spew", 1000.0)])
    assert out[0] == "t=0.000 src=unknown plain gazebo spew"


def test_differing_lines_not_collapsed() -> None:
    out = _drive(
        [
            ("[px4-1] a", 1000.0),
            ("[px4-1] b", 1000.1),
        ]
    )
    assert out == ["t=0.000 src=px4 a", "t=0.100 src=px4 b"]
