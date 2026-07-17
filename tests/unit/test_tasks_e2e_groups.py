from __future__ import annotations

import json

from tasks import _e2e_sim_groups, _fallback_scenario_report


def test_e2e_sim_groups_isolates_scenarios_with_same_config() -> None:
    configs = [
        {
            "scenario": "01_arm_takeoff",
            "vision": "none",
            "overlay": "hover",
            "model": "x500",
            "world": "default",
        },
        {
            "scenario": "02_hover_hold",
            "vision": "none",
            "overlay": "hover",
            "model": "x500",
            "world": "default",
        },
    ]

    assert _e2e_sim_groups(configs) == [
        ("none", "hover", "x500", "default", ["01_arm_takeoff"]),
        ("none", "hover", "x500", "default", ["02_hover_hold"]),
    ]


def test_fallback_report_matches_write_report_shape() -> None:
    data = json.loads(
        _fallback_scenario_report(
            "01_arm_takeoff",
            "crashed_before_report",
            {
                "vision": "none",
                "overlay": "auto_arm",
                "model": "x500",
                "world": "default",
            },
        )
    )

    assert set(data) == {"scenario", "passed", "elapsed_s", "detail"}
    assert data["passed"] is False
    assert data["detail"]["reason"] == "crashed_before_report"
    assert data["detail"]["vision"] == "none"
    assert data["detail"]["overlay"] == "auto_arm"
    assert data["detail"]["model"] == "x500"
    assert data["detail"]["world"] == "default"


def test_fallback_report_is_valid_for_scenario_status() -> None:
    text = _fallback_scenario_report(
        "01_arm_takeoff",
        "no_report_written",
        {"vision": "none", "overlay": "auto_arm", "model": "x500", "world": "default"},
    )

    assert text.endswith("\n")
    assert json.loads(text)["scenario"] == "01_arm_takeoff"
