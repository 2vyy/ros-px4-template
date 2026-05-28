from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

from gz_lifecycle import (
    clear_world_record,
    get_current_world,
    is_gazebo_running,
    reset_world,
    write_current_world,
)


def test_is_gazebo_running_true():
    with patch("gz_lifecycle.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout="Service providers: [gz::transport]", returncode=0)
        assert is_gazebo_running("default") is True
        call_args = mock_run.call_args.args[0]
        assert "/world/default/scene/info" in call_args


def test_is_gazebo_running_false():
    with patch("gz_lifecycle.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout="No service found", returncode=1)
        assert is_gazebo_running("default") is False


def test_is_gazebo_running_timeout():
    with patch("gz_lifecycle.subprocess.run", side_effect=Exception("timeout")):
        assert is_gazebo_running("default") is False


def test_world_tracking(tmp_path):
    with patch("gz_lifecycle._WORLD_FILE", tmp_path / "gz_world.txt"):
        assert get_current_world() is None
        write_current_world("my_world")
        assert get_current_world() == "my_world"
        clear_world_record()
        assert get_current_world() is None


def test_reset_world_success():
    with patch("gz_lifecycle.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        result = reset_world("default")
        assert result is True
        call_args = mock_run.call_args.args[0]
        assert "/world/default/control" in call_args
        assert "reset: {all: true}" in call_args


def test_reset_world_failure():
    with patch("gz_lifecycle.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1)
        assert reset_world("default") is False


def test_reset_world_exception():
    with patch("gz_lifecycle.subprocess.run", side_effect=Exception("timeout")):
        assert reset_world("default") is False
