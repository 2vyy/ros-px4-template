"""Pytest path setup for core.lib imports."""

import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / "src" / "core"))
sys.path.insert(0, str(root / "tools"))


def pytest_report_teststatus(report, config):
    """Suppress passed tests from printing dots/words in non-verbose mode."""
    if config.getoption("verbose") <= 0:
        if report.when == "call" and report.passed:
            return "passed", "", ""
    return None
