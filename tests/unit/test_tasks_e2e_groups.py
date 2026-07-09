from __future__ import annotations

from tasks import _e2e_sim_groups


def test_e2e_sim_groups_isolates_scenarios_with_same_config() -> None:
    configs = [
        {"scenario": "01_arm_takeoff", "vision": "none", "overlay": "hover"},
        {"scenario": "02_hover_hold", "vision": "none", "overlay": "hover"},
    ]

    assert _e2e_sim_groups(configs) == [
        ("none", "hover", ["01_arm_takeoff"]),
        ("none", "hover", ["02_hover_hold"]),
    ]
