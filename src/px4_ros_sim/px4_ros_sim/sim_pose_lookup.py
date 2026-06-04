"""Pure helpers for resolving named poses from Gazebo pose/info."""

from __future__ import annotations

from typing import Protocol


class NamedPose(Protocol):
    name: str


def find_named_pose_in_list(poses: list[NamedPose], model_name: str) -> NamedPose | None:
    """Return the pose entry matching model_name, or None."""
    for entry in poses:
        if entry.name == model_name:
            return entry
    return None
