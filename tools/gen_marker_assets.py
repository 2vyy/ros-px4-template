#!/usr/bin/env python3
"""Deterministic ArUco marker asset generator.

Generates one static Gazebo model per marker ID: a thin, collision-free box
whose top face is textured with a DICT_4X4_50 ArUco code padded with a white
quiet zone.

Physical scale (see plans/043-competition-worlds-assets.md):

- The ArUco code (including its own 1-module black border) renders at
  ``CODE_PIXELS`` (512) px and represents ``CODE_SIZE_M`` (0.2 m) on the
  ground -- this is the size OpenCV's ``marker_size_m`` pose estimation
  expects (see ``lib/aruco_detector.py``).
- A ``QUIET_ZONE_PIXELS`` (64) px pure-white margin is added on every side,
  producing a ``TEXTURE_PIXELS`` (640) px square texture.
- The physical surface therefore covers ``SURFACE_SIZE_M`` = ``CODE_SIZE_M``
  * ``TEXTURE_PIXELS`` / ``CODE_PIXELS`` = 0.25 m per side.

Rendering is pure (no filesystem I/O); ``main()`` and ``write_model`` do the
writing so tests can target a temporary directory instead of the repository.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import cv2
import numpy as np

DICTIONARY_ID = cv2.aruco.DICT_4X4_50
MARKER_IDS: tuple[int, ...] = (0, 1, 2)

CODE_PIXELS = 512
QUIET_ZONE_PIXELS = 64
TEXTURE_PIXELS = CODE_PIXELS + 2 * QUIET_ZONE_PIXELS  # 640

CODE_SIZE_M = 0.2
SURFACE_SIZE_M = CODE_SIZE_M * TEXTURE_PIXELS / CODE_PIXELS  # 0.25
MODEL_THICKNESS_M = 0.01

_MODEL_NAME_TEMPLATE = "aruco_marker_{id}"
_TEXTURE_NAME_TEMPLATE = "aruco_marker_{id}.png"


def model_name(marker_id: int) -> str:
    return _MODEL_NAME_TEMPLATE.format(id=marker_id)


def texture_name(marker_id: int) -> str:
    return _TEXTURE_NAME_TEMPLATE.format(id=marker_id)


def model_uri(marker_id: int) -> str:
    """The ``model://`` URI a world file uses to include this model."""
    return f"model://{model_name(marker_id)}"


def render_code_image(marker_id: int) -> np.ndarray:
    """Render the raw DICT_4X4_50 code (with its own black border) at CODE_PIXELS."""
    aruco_dict = cv2.aruco.getPredefinedDictionary(DICTIONARY_ID)
    img = np.zeros((CODE_PIXELS, CODE_PIXELS), dtype=np.uint8)
    cv2.aruco.generateImageMarker(aruco_dict, marker_id, CODE_PIXELS, img, 1)
    return img


def render_texture(marker_id: int) -> np.ndarray:
    """Pad the raw code with a pure-white quiet zone, producing a TEXTURE_PIXELS square.

    Returned array is 3-channel BGR (grayscale replicated) at TEXTURE_PIXELS
    per side, suitable for ``cv2.imwrite``.
    """
    code = render_code_image(marker_id)
    canvas = np.full((TEXTURE_PIXELS, TEXTURE_PIXELS), 255, dtype=np.uint8)
    canvas[
        QUIET_ZONE_PIXELS : QUIET_ZONE_PIXELS + CODE_PIXELS,
        QUIET_ZONE_PIXELS : QUIET_ZONE_PIXELS + CODE_PIXELS,
    ] = code
    return cv2.cvtColor(canvas, cv2.COLOR_GRAY2BGR)


def build_model_config(marker_id: int) -> str:
    """Deterministic ``model.config`` content; no timestamps or host paths."""
    return (
        '<?xml version="1.0"?>\n'
        "<model>\n"
        f"  <name>{model_name(marker_id)}</name>\n"
        "  <version>1.0</version>\n"
        '  <sdf version="1.9">model.sdf</sdf>\n'
        "  <description>"
        f"DICT_4X4_50 ArUco marker id {marker_id}. "
        f"Black code {CODE_SIZE_M} m square ({CODE_PIXELS} px); "
        f"white quiet zone {QUIET_ZONE_PIXELS} px per side; "
        f"total padded surface {SURFACE_SIZE_M} m square ({TEXTURE_PIXELS} px)."
        "</description>\n"
        "</model>\n"
    )


def build_model_sdf(marker_id: int) -> str:
    """Deterministic ``model.sdf``: a static, collision-free, thin textured box."""
    name = model_name(marker_id)
    texture = texture_name(marker_id)
    return (
        '<?xml version="1.0"?>\n'
        '<sdf version="1.9">\n'
        f'  <model name="{name}">\n'
        "    <static>true</static>\n"
        '    <link name="link">\n'
        '      <visual name="visual">\n'
        "        <geometry>\n"
        "          <box>\n"
        f"            <size>{SURFACE_SIZE_M} {SURFACE_SIZE_M} {MODEL_THICKNESS_M}</size>\n"
        "          </box>\n"
        "        </geometry>\n"
        "        <material>\n"
        "          <pbr>\n"
        "            <metal>\n"
        f"              <albedo_map>materials/textures/{texture}</albedo_map>\n"
        "              <roughness>1.0</roughness>\n"
        "              <metalness>0.0</metalness>\n"
        "            </metal>\n"
        "          </pbr>\n"
        "        </material>\n"
        "      </visual>\n"
        "    </link>\n"
        "  </model>\n"
        "</sdf>\n"
    )


def write_model(marker_id: int, output_root: Path) -> Path:
    """Write one model tree under ``output_root/aruco_marker_<id>/``. Returns its path."""
    model_dir = output_root / model_name(marker_id)
    textures_dir = model_dir / "materials" / "textures"
    textures_dir.mkdir(parents=True, exist_ok=True)

    (model_dir / "model.config").write_text(build_model_config(marker_id), encoding="utf-8")
    (model_dir / "model.sdf").write_text(build_model_sdf(marker_id), encoding="utf-8")

    texture_path = textures_dir / texture_name(marker_id)
    cv2.imwrite(str(texture_path), render_texture(marker_id))

    return model_dir


def generate_all(output_root: Path, marker_ids: tuple[int, ...] = MARKER_IDS) -> list[Path]:
    return [write_model(marker_id, output_root) for marker_id in marker_ids]


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    default_root = Path(__file__).resolve().parents[1] / "sim" / "models"
    parser.add_argument("--output-root", type=Path, default=default_root)
    args = parser.parse_args(argv)

    written = generate_all(args.output_root)
    for path in written:
        print(f"[gen_marker_assets] wrote {path}")


if __name__ == "__main__":
    main()
