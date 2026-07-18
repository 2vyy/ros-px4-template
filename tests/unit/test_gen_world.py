"""Unit tests for the challenge-spec world generator."""

from __future__ import annotations

import re
import sys as _sys
from pathlib import Path

import pytest
import yaml

_ROOT = Path(__file__).resolve().parents[2]
_TOOLS_DIR = _ROOT / "tools"
if str(_TOOLS_DIR) not in _sys.path:
    _sys.path.insert(0, str(_TOOLS_DIR))

import gen_world as gw  # noqa: E402

_MARKER_FIELD_SPEC = _ROOT / "sim" / "worlds" / "specs" / "marker_field.yaml"
_MARKER_FIELD_SDF = _ROOT / "sim" / "worlds" / "marker_field.sdf"
_MARKER_FIELD_MAP = _ROOT / "config" / "marker_maps" / "marker_field.yaml"
_DEFAULT_SDF = _ROOT / "sim" / "worlds" / "default.sdf"


def _load_marker_field_spec() -> dict:
    return gw.load_spec(_MARKER_FIELD_SPEC)


def test_marker_field_round_trip() -> None:
    """Committed marker_field is the golden oracle (plans/043 / 072)."""
    spec = _load_marker_field_spec()
    rel = "sim/worlds/specs/marker_field.yaml"
    assert (
        gw.build_world_sdf(spec, relative_spec=rel).encode("utf-8")
        == _MARKER_FIELD_SDF.read_bytes()
    )
    assert (
        gw.build_marker_map(spec, relative_spec=rel).encode("utf-8")
        == _MARKER_FIELD_MAP.read_bytes()
    )


def test_physics_block_matches_default_world() -> None:
    default = _DEFAULT_SDF.read_text(encoding="utf-8")
    m = re.search(r"<physics type=\"ode\">.*?</physics>", default, flags=re.DOTALL)
    assert m is not None
    physics = m.group(0)
    spec = _load_marker_field_spec()
    generated = gw.build_world_sdf(spec, relative_spec="sim/worlds/specs/marker_field.yaml")
    assert physics in generated


def test_map_and_world_agree() -> None:
    spec = {
        "name": "agree_test",
        "markers": [
            {"id": 0, "x": 8.0, "y": 0.0},
            {"id": 5, "x": -4.0, "y": 6.0},
            {"id": 7, "x": 2.0, "y": -9.0},
        ],
        "obstacles": [],
    }
    sdf = gw.build_world_sdf(spec, relative_spec="sim/worlds/specs/agree_test.yaml")
    map_text = gw.build_marker_map(spec, relative_spec="sim/worlds/specs/agree_test.yaml")
    map_data = yaml.safe_load(map_text)
    sdf_ids = {int(m) for m in re.findall(r"model://aruco_marker_(\d+)", sdf)}
    map_ids = {int(k) for k in map_data["markers"]}
    assert sdf_ids == map_ids == {0, 5, 7}
    for mid, pose in map_data["markers"].items():
        assert f"model://aruco_marker_{mid}" in sdf
        assert f"<pose>{pose['x']:g} {pose['y']:g} 0.005 0 0 0</pose>" in sdf


def test_origin_column_clear_rejected() -> None:
    spec = {
        "name": "bad_pylon",
        "markers": [],
        "obstacles": [
            {
                "type": "cylinder",
                "name": "pylon_near",
                "x": 0.5,
                "y": 0.0,
                "radius": 0.3,
                "height": 2.0,
            }
        ],
    }
    with pytest.raises(SystemExit) as exc:
        gw.validate_spec(spec, check_models=False)
    assert exc.value.code == 2


def test_unknown_marker_model_names_gen_markers(tmp_path: Path) -> None:
    models = tmp_path / "models"
    models.mkdir()
    # id 0 present, id 7 missing
    (models / "aruco_marker_0").mkdir()
    spec = {
        "name": "needs_marker",
        "markers": [
            {"id": 0, "x": 8.0, "y": 0.0},
            {"id": 7, "x": -6.0, "y": 10.0},
        ],
        "obstacles": [],
    }
    with pytest.raises(SystemExit) as exc:
        gw.validate_spec(spec, models_dir=models, check_models=True)
    assert exc.value.code == 2
    # Message is printed to stderr; re-run capturing via write path for text.
    import io
    from contextlib import redirect_stderr

    buf = io.StringIO()
    with redirect_stderr(buf), pytest.raises(SystemExit):
        gw.validate_spec(spec, models_dir=models, check_models=True)
    assert "gen-markers" in buf.getvalue()
