"""Unit tests for the deterministic ArUco marker asset generator."""

from __future__ import annotations

import filecmp
import sys as _sys
from pathlib import Path

import cv2
import numpy as np
import pytest

_ROOT = Path(__file__).resolve().parents[2]
_TOOLS_DIR = _ROOT / "tools"
if str(_TOOLS_DIR) not in _sys.path:
    _sys.path.insert(0, str(_TOOLS_DIR))

import gen_marker_assets as gma  # noqa: E402


def test_generator_matches_committed_models() -> None:
    """The committed models are live-verified (plans/062); the generator must
    reproduce them byte-for-byte so a regeneration can never regress the
    emissive_map fix."""
    for marker_id in (0, 1, 2):
        committed = _ROOT / "sim" / "models" / f"aruco_marker_{marker_id}" / "model.sdf"
        assert gma.build_model_sdf(marker_id).encode("utf-8") == committed.read_bytes()


def test_physical_scale_constants() -> None:
    assert gma.CODE_PIXELS == 512
    assert gma.QUIET_ZONE_PIXELS == 64
    assert gma.TEXTURE_PIXELS == 640
    assert gma.CODE_SIZE_M == 0.2
    assert gma.SURFACE_SIZE_M == pytest.approx(0.25)


def test_model_uri() -> None:
    assert gma.model_uri(0) == "model://aruco_marker_0"
    assert gma.model_uri(2) == "model://aruco_marker_2"


@pytest.mark.parametrize("marker_id", gma.MARKER_IDS)
def test_texture_dimensions(marker_id: int) -> None:
    texture = gma.render_texture(marker_id)
    assert texture.shape == (640, 640, 3)


@pytest.mark.parametrize("marker_id", gma.MARKER_IDS)
def test_quiet_zone_is_pure_white(marker_id: int) -> None:
    texture = gma.render_texture(marker_id)
    border = gma.QUIET_ZONE_PIXELS

    top = texture[:border, :, :]
    bottom = texture[-border:, :, :]
    left = texture[:, :border, :]
    right = texture[:, -border:, :]

    for region in (top, bottom, left, right):
        assert np.all(region == 255)


@pytest.mark.parametrize("marker_id", gma.MARKER_IDS)
def test_code_area_is_not_all_white(marker_id: int) -> None:
    texture = gma.render_texture(marker_id)
    border = gma.QUIET_ZONE_PIXELS
    code_region = texture[border : border + gma.CODE_PIXELS, border : border + gma.CODE_PIXELS, :]
    assert not np.all(code_region == 255)
    assert np.any(code_region < 128)


def test_generate_all_writes_expected_tree(tmp_path: Path) -> None:
    written = gma.generate_all(tmp_path)
    assert len(written) == len(gma.MARKER_IDS)

    for marker_id, model_dir in zip(gma.MARKER_IDS, written, strict=True):
        assert model_dir == tmp_path / gma.model_name(marker_id)
        assert (model_dir / "model.config").is_file()
        assert (model_dir / "model.sdf").is_file()
        texture_path = model_dir / "materials" / "textures" / gma.texture_name(marker_id)
        assert texture_path.is_file()

        image = cv2.imread(str(texture_path))
        assert image.shape == (640, 640, 3)

        config_text = (model_dir / "model.config").read_text(encoding="utf-8")
        assert f"{gma.CODE_SIZE_M} m" in config_text
        assert f"{gma.SURFACE_SIZE_M} m" in config_text

        sdf_text = (model_dir / "model.sdf").read_text(encoding="utf-8")
        assert "<plane>" in sdf_text
        assert f"<size>{gma.SURFACE_SIZE_M} {gma.SURFACE_SIZE_M}</size>" in sdf_text
        assert gma.texture_name(marker_id) in sdf_text


def test_no_nondeterministic_metadata(tmp_path: Path) -> None:
    written = gma.generate_all(tmp_path)
    for model_dir in written:
        for text_file in ("model.config", "model.sdf"):
            content = (model_dir / text_file).read_text(encoding="utf-8")
            assert "/home/" not in content
            assert "/tmp" not in content
            assert str(tmp_path) not in content


def test_two_runs_are_byte_identical(tmp_path: Path) -> None:
    run_a = tmp_path / "run_a"
    run_b = tmp_path / "run_b"
    gma.generate_all(run_a)
    gma.generate_all(run_b)

    for marker_id in gma.MARKER_IDS:
        name = gma.model_name(marker_id)
        dir_a = run_a / name
        dir_b = run_b / name

        for rel in (
            "model.config",
            "model.sdf",
            f"materials/textures/{gma.texture_name(marker_id)}",
        ):
            assert filecmp.cmp(dir_a / rel, dir_b / rel, shallow=False), rel


def test_regenerating_same_output_root_is_idempotent(tmp_path: Path) -> None:
    gma.generate_all(tmp_path)
    first_bytes = {p: p.read_bytes() for p in sorted(tmp_path.rglob("*")) if p.is_file()}
    gma.generate_all(tmp_path)
    second_bytes = {p: p.read_bytes() for p in sorted(tmp_path.rglob("*")) if p.is_file()}
    assert first_bytes == second_bytes
