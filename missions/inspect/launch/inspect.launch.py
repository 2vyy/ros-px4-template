"""Inspect mission: inspect_aruco world, vision, and marker-hover profile overlay.

Wraps sim_full.launch.py with defaults for the ArUco inspect demo.
Use via: ros2 launch missions/inspect/launch/inspect.launch.py
Or: just sim inspect (tasks.py passes the same launch arguments).
"""

from __future__ import annotations

from pathlib import Path

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration

_PROJECT_ROOT = Path(__file__).resolve().parents[3]


def generate_launch_description() -> LaunchDescription:
    sim_launch = PythonLaunchDescriptionSource(
        str(_PROJECT_ROOT / "sim" / "launch" / "sim_full.launch.py")
    )
    return LaunchDescription(
        [
            DeclareLaunchArgument("headless", default_value="false"),
            DeclareLaunchArgument("log_dir", default_value=str(_PROJECT_ROOT / "logs")),
            IncludeLaunchDescription(
                sim_launch,
                launch_arguments={
                    "world": "inspect_aruco",
                    "model": "x500",
                    "enable_vision": "true",
                    "headless": LaunchConfiguration("headless"),
                    "log_dir": LaunchConfiguration("log_dir"),
                    "param_overlay": "inspect",
                }.items(),
            ),
        ]
    )
