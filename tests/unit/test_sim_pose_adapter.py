"""Unit tests for sim_pose_adapter pose extraction."""

from __future__ import annotations

from types import SimpleNamespace

from px4_ros_sim.sim_pose_lookup import find_named_pose_in_list


def _pose(name: str, z: float) -> SimpleNamespace:
    return SimpleNamespace(name=name, position=SimpleNamespace(z=z))


def test_find_named_pose_in_list_returns_match() -> None:
    found = find_named_pose_in_list(
        [_pose("ground_plane", 0.0), _pose("x500_0", 1.5)],
        "x500_0",
    )
    assert found is not None
    assert getattr(found, "position").z == 1.5


def test_find_named_pose_in_list_missing_returns_none() -> None:
    assert find_named_pose_in_list([_pose("ground_plane", 0.0)], "x500_0") is None
