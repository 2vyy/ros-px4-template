from __future__ import annotations

import ast
from pathlib import Path


def test_scenario_scripts_use_direct_runnable_common_imports() -> None:
    """Scenario scripts run as files, so they must import sibling _common."""
    scenario_dir = Path("tests/scenarios")
    offenders: list[str] = []
    for script in scenario_dir.glob("[0-9][0-9]_*.py"):
        tree = ast.parse(script.read_text(encoding="utf-8"), filename=str(script))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "tests.scenarios._common":
                offenders.append(str(script))

    assert offenders == []
