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
                "gz",
                "service",
                "-s",
                f"/world/{world}/control",
                "--reqtype",
                "gz.msgs.WorldControl",
                "--reptype",
                "gz.msgs.Boolean",
                "--timeout",
                "3000",  # gz CLI timeout in ms; Python timeout below is the backstop in seconds
                "--req",
                "reset: {all: true}, pause: false",
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


def is_model_present(world: str, model: str) -> bool:
    """Return True if the model is currently present in Gazebo."""
    try:
        r = subprocess.run(
            ["gz", "model", "--list"],
            capture_output=True,
            text=True,
            timeout=3,
        )
        if r.returncode != 0:
            return False
        for line in r.stdout.splitlines():
            line_str = line.strip()
            if line_str.startswith("-") or line_str.startswith("*"):
                name = line_str.lstrip("-* ").strip()
                if name == model:
                    return True
        return False
    except Exception:
        return False
