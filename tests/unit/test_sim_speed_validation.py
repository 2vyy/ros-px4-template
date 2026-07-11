from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tasks import app
from typer.testing import CliRunner

runner = CliRunner()


def test_sim_has_no_speed_flag():
    """Guard against reintroduction: the sim speed flag was removed because ANY
    live gz set_physics call latently corrupts PX4's altitude estimate
    (plans/065 spike truth table). Physics comes solely from the world SDF."""
    result = runner.invoke(app, ["sim", "--speed", "1.0"])
    assert result.exit_code == 2
    assert "no such option" in result.output.lower()
