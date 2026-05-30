"""Marker pose → hover target with debounce helpers."""

from __future__ import annotations

from dataclasses import dataclass

from ros_px4_template_core.lib.waypoint_mission import EnuPoint, MarkerConfig


@dataclass
class MarkerTracker:
    """Track consecutive valid marker frames and stale loss."""

    consecutive_valid: int = 0
    lost_since: float | None = None

    def note_valid(self, now: float) -> None:
        self.consecutive_valid += 1
        # Do NOT reset lost_since here: once the loss clock starts, interleaved
        # valid frames from a flaky detector must not restart the debounce timer.

    def note_invalid(self, now: float) -> None:
        self.consecutive_valid = 0
        if self.lost_since is None:
            self.lost_since = now

    def acquired(self, cfg: MarkerConfig) -> bool:
        return self.consecutive_valid >= cfg.acquire_frames

    def lost_debounced(self, cfg: MarkerConfig, now: float) -> bool:
        if self.lost_since is None:
            return False
        return (now - self.lost_since) >= cfg.lost_timeout_s


def marker_hover_target(marker: EnuPoint, cfg: MarkerConfig) -> EnuPoint:
    off = cfg.hold_offset_enu
    return EnuPoint(
        marker.x + off.x,
        marker.y + off.y,
        marker.z + off.z,
    )


def pose_to_enu(position: tuple[float, float, float]) -> EnuPoint:
    return EnuPoint(position[0], position[1], position[2])
