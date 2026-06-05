"""Unit tests for mission core types + registry."""

from __future__ import annotations

import math

import pytest
from ros_px4_template_core.lib import mission as mission_pkg  # noqa: F401 (populates registry)
from ros_px4_template_core.lib.mission import registry
from ros_px4_template_core.lib.mission.commands import BehaviorResult, GoTo, Hold
from ros_px4_template_core.lib.mission.detection import body_flu_to_enu_offset


def test_goto_is_frozen() -> None:
    g = GoTo(1.0, 2.0, 3.0)
    assert (g.x, g.y, g.z, g.yaw) == (1.0, 2.0, 3.0, None)
    with pytest.raises(AttributeError):
        g.x = 9.0  # type: ignore


def test_behavior_result_carries_signals() -> None:
    r = BehaviorResult(command=Hold(), signals={"reached": True})
    assert isinstance(r.command, Hold)
    assert r.signals["reached"] is True


def test_body_flu_to_enu_offset_yaw_zero_is_identity_axes() -> None:
    # yaw_enu=0 means body-forward points East. forward=1,left=0 -> (E=1, N=0).
    e, n = body_flu_to_enu_offset((1.0, 0.0, 0.0), 0.0)
    assert math.isclose(e, 1.0, abs_tol=1e-9)
    assert math.isclose(n, 0.0, abs_tol=1e-9)
    # left=1 (body +Y) at yaw 0 -> North.
    e, n = body_flu_to_enu_offset((0.0, 1.0, 0.0), 0.0)
    assert math.isclose(e, 0.0, abs_tol=1e-9)
    assert math.isclose(n, 1.0, abs_tol=1e-9)


def test_body_flu_to_enu_offset_yaw_90_rotates() -> None:
    # yaw_enu=pi/2 means body-forward points North. forward=1 -> (E=0, N=1).
    e, n = body_flu_to_enu_offset((1.0, 0.0, 0.0), math.pi / 2)
    assert math.isclose(e, 0.0, abs_tol=1e-9)
    assert math.isclose(n, 1.0, abs_tol=1e-9)


def test_registry_lookup_and_unknown() -> None:
    assert callable(registry.get_behavior("hold"))
    assert callable(registry.get_guard("armed_at_altitude"))
    with pytest.raises(KeyError):
        registry.get_behavior("does_not_exist")
    with pytest.raises(KeyError):
        registry.get_guard("does_not_exist")
