"""Unit tests for marker_target."""

from __future__ import annotations

from ros_px4_template_core.lib.marker_target import MarkerTracker, marker_hover_target
from ros_px4_template_core.lib.waypoint_mission import EnuPoint, MarkerConfig


def test_marker_acquire_and_lost() -> None:
    cfg = MarkerConfig(
        hold_offset_enu=EnuPoint(0, 0, 1.5),
        acquire_frames=3,
        lost_timeout_s=1.0,
    )
    tr = MarkerTracker()
    tr.note_valid(0.0)
    tr.note_valid(0.1)
    assert not tr.acquired(cfg)
    tr.note_valid(0.2)
    assert tr.acquired(cfg)
    tr.note_invalid(1.0)
    assert not tr.lost_debounced(cfg, 1.5)
    assert tr.lost_debounced(cfg, 2.1)


def test_hover_offset() -> None:
    cfg = MarkerConfig(hold_offset_enu=EnuPoint(0, 0, 1.5))
    t = marker_hover_target(EnuPoint(8, 0, 0), cfg)
    assert t.z == 1.5


def test_flaky_detector_eventually_debounces() -> None:
    """A detector that alternates valid/invalid must still debounce after lost_timeout_s."""
    cfg = MarkerConfig(
        hold_offset_enu=EnuPoint(0, 0, 1.5),
        acquire_frames=3,
        lost_timeout_s=1.0,
    )
    tr = MarkerTracker()

    # Seed as acquired
    for _ in range(3):
        tr.note_valid(0.0)

    # First invalid frame starts the debounce clock
    tr.note_invalid(1.0)  # lost_since = 1.0

    # Alternating valid/invalid frames — should NOT reset the clock
    for i in range(10):
        tr.note_valid(1.0 + i * 0.05)
        tr.note_invalid(1.0 + i * 0.05 + 0.025)

    # With bug: lost_since resets to ~1.475; (2.1-1.475)=0.625 < 1.0 → False → test fails ✓
    # With fix: lost_since anchored at 1.0; (2.1-1.0)=1.1 >= 1.0 → True → test passes ✓
    assert tr.lost_debounced(cfg, 2.1)
