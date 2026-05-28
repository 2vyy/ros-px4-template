"""Gazebo server lifecycle helpers — detection, world tracking, world reset."""
from __future__ import annotations

import subprocess
from pathlib import Path

_WORLD_FILE = Path(__file__).resolve().parents[1] / "logs" / "gz_world.txt"
_GZ_TIMEOUT_S = 3


def is_gazebo_running(world: str) -> bool:
    """Return True if gz sim is currently serving the given world."""
    try:
        r = subprocess.run(
            ["gz", "service", "-i", "--service", f"/world/{world}/scene/info"],
            capture_output=True,
            text=True,
            timeout=_GZ_TIMEOUT_S,
        )
        return "Service providers" in r.stdout
    except Exception:
        return False


def get_current_world() -> str | None:
    """Return world name from logs/gz_world.txt, or None if absent/empty."""
    try:
        text = _WORLD_FILE.read_text().strip()
        return text or None
    except FileNotFoundError:
        return None


def write_current_world(world: str) -> None:
    """Record the current world name in logs/gz_world.txt."""
    _WORLD_FILE.parent.mkdir(parents=True, exist_ok=True)
    _WORLD_FILE.write_text(world)


def clear_world_record() -> None:
    """Remove logs/gz_world.txt (called on full kill)."""
    _WORLD_FILE.unlink(missing_ok=True)


def reset_world(world: str) -> bool:
    """Send WorldControl reset to the running gz server. Return True on success."""
    try:
        r = subprocess.run(
            [
                "gz", "service",
                "-s", f"/world/{world}/control",
                "--reqtype", "gz.msgs.WorldControl",
                "--reptype", "gz.msgs.Boolean",
                "--timeout", "3000",
                "--req", "reset: {all: true}",
            ],
            capture_output=True,
            text=True,
            timeout=_GZ_TIMEOUT_S + 1,
        )
        return r.returncode == 0
    except Exception:
        return False


def gazebo_matches(world: str) -> bool:
    """Return True if Gazebo is running AND serving the requested world."""
    current = get_current_world()
    if current != world:
        return False
    return is_gazebo_running(world)
