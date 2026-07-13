"""_world_sdf classifies repo vs PX4-shipped worlds (drives the boot path).

A repo world (SDF in sim/worlds) must be flagged is_repo so _start_gz_px4.sh
takes the pre-start-paused branch; a PX4-shipped world must NOT, so the original
lockstep boot stays byte-identical. See plans/049.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

pytest.importorskip("launch")
pytest.importorskip("launch_ros")

_LAUNCH = Path(__file__).resolve().parents[2] / "sim" / "launch" / "sim_full.launch.py"


def _load():
    spec = importlib.util.spec_from_file_location("sim_full_launch", _LAUNCH)
    assert spec is not None
    assert spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _make_tree(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "repo"
    (root / "sim" / "worlds").mkdir(parents=True)
    px4 = tmp_path / "px4"
    (px4 / "Tools" / "simulation" / "gz" / "worlds").mkdir(parents=True)
    return root, px4


def test_repo_world_is_flagged_and_pathed(tmp_path):
    mod = _load()
    root, px4 = _make_tree(tmp_path)
    (root / "sim" / "worlds" / "marker_field.sdf").write_text("<sdf/>")
    sdf, worlds_dir, is_repo = mod._world_sdf(root, str(px4), "marker_field")
    assert is_repo is True
    assert sdf == str(root / "sim" / "worlds" / "marker_field.sdf")
    assert worlds_dir == str(root / "sim" / "worlds")


def test_px4_world_is_not_repo(tmp_path):
    mod = _load()
    root, px4 = _make_tree(tmp_path)  # no default.sdf in the repo tree
    sdf, worlds_dir, is_repo = mod._world_sdf(root, str(px4), "default")
    assert is_repo is False
    assert sdf == str(px4 / "Tools" / "simulation" / "gz" / "worlds" / "default.sdf")
    assert worlds_dir == str(px4 / "Tools" / "simulation" / "gz" / "worlds")
