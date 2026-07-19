#!/usr/bin/env python3
"""Challenge-spec world generator.

Reads a small YAML challenge spec and writes:

- ``sim/worlds/<name>.sdf`` — Gazebo world with the flight-verified skeleton
  (physics / gravity / magnetic field / ground / light / spherical coords)
  plus optional static obstacles and ArUco marker includes.
- ``config/marker_maps/<name>.yaml`` — marker map from the SAME marker list,
  so world poses and map entries cannot disagree.

Pure builders; I/O only in ``write_*`` / ``main``. Usage errors exit 2.
"""

from __future__ import annotations

import argparse
import math
import re
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WORLDS_DIR = ROOT / "sim" / "worlds"
DEFAULT_MAPS_DIR = ROOT / "config" / "marker_maps"
DEFAULT_MODELS_DIR = ROOT / "sim" / "models"

MARKER_SURFACE_Z = 0.005
ORIGIN_CLEARANCE_M = 1.5
VALID_MARKER_ID = range(0, 50)
_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*$")

# Skeleton body inside <world>, verbatim from the committed marker_field.sdf
# (physics through spherical_coordinates). default.sdf shares the same
# physics block; unit tests pin that independently.
_SKELETON = """\
    <physics type="ode">
      <max_step_size>0.004</max_step_size>
      <real_time_factor>1.0</real_time_factor>
      <real_time_update_rate>250</real_time_update_rate>
    </physics>
    <gravity>0 0 -9.8</gravity>
    <magnetic_field>6e-06 2.3e-05 -4.2e-05</magnetic_field>
    <atmosphere type="adiabatic"/>
    <scene>
      <grid>false</grid>
      <ambient>0.4 0.4 0.4 1</ambient>
      <background>0.7 0.7 0.7 1</background>
      <shadows>true</shadows>
    </scene>

    <model name="ground_plane">
      <static>true</static>
      <link name="link">
        <collision name="collision">
          <geometry>
            <plane>
              <normal>0 0 1</normal>
              <size>1 1</size>
            </plane>
          </geometry>
          <surface>
            <friction><ode/></friction>
            <bounce/>
            <contact/>
          </surface>
        </collision>
        <visual name="visual">
          <geometry>
            <plane>
              <normal>0 0 1</normal>
              <size>500 500</size>
            </plane>
          </geometry>
          <material>
            <ambient>0.8 0.8 0.8 1</ambient>
            <diffuse>0.8 0.8 0.8 1</diffuse>
            <specular>0.8 0.8 0.8 1</specular>
          </material>
        </visual>
        <pose>0 0 0 0 0 0</pose>
        <inertial>
          <pose>0 0 0 0 0 0</pose>
          <mass>1</mass>
          <inertia><ixx>1</ixx><ixy>0</ixy><ixz>0</ixz><iyy>1</iyy><iyz>0</iyz><izz>1</izz></inertia>
        </inertial>
        <enable_wind>false</enable_wind>
      </link>
      <pose>0 0 0 0 0 0</pose>
      <self_collide>false</self_collide>
    </model>

    <light name="sunUTC" type="directional">
      <pose>0 0 500 0 0 0</pose>
      <cast_shadows>true</cast_shadows>
      <intensity>1</intensity>
      <direction>0.001 0.625 -0.78</direction>
      <diffuse>0.904 0.904 0.904 1</diffuse>
      <specular>0.271 0.271 0.271 1</specular>
      <attenuation>
        <range>2000</range>
        <linear>0</linear>
        <constant>1</constant>
        <quadratic>0</quadratic>
      </attenuation>
      <spot>
        <inner_angle>0</inner_angle>
        <outer_angle>0</outer_angle>
        <falloff>0</falloff>
      </spot>
    </light>

    <spherical_coordinates>
      <surface_model>EARTH_WGS84</surface_model>
      <world_frame_orientation>ENU</world_frame_orientation>
      <latitude_deg>47.397971057728974</latitude_deg>
      <longitude_deg>8.546163739800146</longitude_deg>
      <elevation>0</elevation>
    </spherical_coordinates>"""


def _usage_error(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    raise SystemExit(2)


def _fmt_pose_xy(x: float, y: float) -> str:
    """Format x/y for SDF pose (strip trailing .0 on whole numbers)."""
    return f"{x:g} {y:g}"


def _point_to_aabb_distance(
    px: float, py: float, cx: float, cy: float, hx: float, hy: float
) -> float:
    dx = max(abs(px - cx) - hx, 0.0)
    dy = max(abs(py - cy) - hy, 0.0)
    return math.hypot(dx, dy)


def _obstacle_clearance_m(obs: dict[str, Any]) -> float:
    otype = obs["type"]
    x = float(obs["x"])
    y = float(obs["y"])
    if otype == "cylinder":
        return math.hypot(x, y) - float(obs["radius"])
    if otype == "box":
        size = obs["size"]
        hx = float(size[0]) / 2.0
        hy = float(size[1]) / 2.0
        return _point_to_aabb_distance(0.0, 0.0, x, y, hx, hy)
    _usage_error(f"unknown obstacle type {otype!r} (want cylinder|box)")
    raise AssertionError("unreachable")


def load_spec(path: Path) -> dict[str, Any]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        _usage_error(f"spec must be a mapping: {path}")
    raw["_spec_path"] = str(path)
    return raw


def validate_spec(
    spec: dict[str, Any],
    *,
    models_dir: Path = DEFAULT_MODELS_DIR,
    check_models: bool = True,
) -> None:
    name = spec.get("name")
    if not isinstance(name, str) or not _NAME_RE.match(name):
        _usage_error(f"world name must be a valid filename starting with a letter, got {name!r}")
    if name == "default":
        _usage_error("world name must not be 'default' (flight-verified baseline is hand-written)")

    markers = spec.get("markers") or []
    if not isinstance(markers, list):
        _usage_error("markers must be a list")

    seen_ids: set[int] = set()
    for m in markers:
        if not isinstance(m, dict) or "id" not in m or "x" not in m or "y" not in m:
            _usage_error(f"marker entries need id, x, y — got {m!r}")
        mid = int(m["id"])
        if mid not in VALID_MARKER_ID:
            _usage_error(f"marker id {mid} out of DICT_4X4_50 range [0, 49]")
        if mid in seen_ids:
            _usage_error(f"duplicate marker id {mid}")
        seen_ids.add(mid)
        if check_models:
            model_path = models_dir / f"aruco_marker_{mid}"
            if not model_path.is_dir():
                _usage_error(f"missing model {model_path} — run: just gen-markers --ids {mid}")

    obstacles = spec.get("obstacles") or []
    if not isinstance(obstacles, list):
        _usage_error("obstacles must be a list")

    seen_names: set[str] = set()
    for obs in obstacles:
        if not isinstance(obs, dict):
            _usage_error(f"obstacle must be a mapping, got {obs!r}")
        oname = obs.get("name")
        if not isinstance(oname, str) or not oname:
            _usage_error(f"obstacle needs a non-empty name, got {obs!r}")
        if oname in seen_names:
            _usage_error(f"duplicate obstacle name {oname!r}")
        seen_names.add(oname)
        otype = obs.get("type")
        if otype not in ("cylinder", "box"):
            _usage_error(f"obstacle type must be cylinder|box, got {otype!r}")
        if "x" not in obs or "y" not in obs:
            _usage_error(f"obstacle {oname!r} needs x, y")
        if otype == "cylinder":
            if "radius" not in obs or "height" not in obs:
                _usage_error(f"cylinder {oname!r} needs radius, height")
        else:
            size = obs.get("size")
            if not (isinstance(size, list) and len(size) == 3):
                _usage_error(f"box {oname!r} needs size: [sx, sy, sz]")
        clearance = _obstacle_clearance_m(obs)
        if clearance < ORIGIN_CLEARANCE_M:
            _usage_error(
                f"obstacle {oname!r} intrudes on the origin climb column "
                f"(clearance {clearance:.3f} m < {ORIGIN_CLEARANCE_M} m; "
                "origin climb column stays clear)"
            )


def _header_comment(spec: dict[str, Any], *, relative_spec: str) -> str:
    markers = spec.get("markers") or []
    layout_lines = [
        f"    marker {int(m['id'])}: ({float(m['x']):g}, {float(m['y']):g}, {MARKER_SURFACE_Z})"
        for m in markers
    ]
    layout = "\n".join(layout_lines) if layout_lines else "    (none)"
    return f"""\
<!--
  Generated by tools/gen_world.py from {relative_spec}.
  Do not edit by hand; re-run: just gen-world --spec {relative_spec}

  Anchored-ENU marker layout (origin = takeoff point):
{layout}

  Physics, gravity, magnetic field, ground plane, light, and spherical
  coordinates are copied verbatim from the flight-verified default.sdf.
-->"""


def _build_cylinder_model(obs: dict[str, Any]) -> str:
    name = obs["name"]
    x = float(obs["x"])
    y = float(obs["y"])
    radius = float(obs["radius"])
    height = float(obs["height"])
    z = height / 2.0
    pose = f"{_fmt_pose_xy(x, y)} {z:g} 0 0 0"
    return f"""\
    <model name="{name}">
      <static>true</static>
      <pose>{pose}</pose>
      <link name="link">
        <collision name="collision">
          <geometry>
            <cylinder><radius>{radius:g}</radius><length>{height:g}</length></cylinder>
          </geometry>
          <surface>
            <friction><ode/></friction>
            <bounce/>
            <contact/>
          </surface>
        </collision>
        <visual name="visual">
          <geometry>
            <cylinder><radius>{radius:g}</radius><length>{height:g}</length></cylinder>
          </geometry>
          <material>
            <ambient>0.9 0.5 0.1 1</ambient>
            <diffuse>0.9 0.5 0.1 1</diffuse>
            <specular>0.9 0.5 0.1 1</specular>
          </material>
        </visual>
      </link>
    </model>"""


def _build_box_model(obs: dict[str, Any]) -> str:
    name = obs["name"]
    x = float(obs["x"])
    y = float(obs["y"])
    sx, sy, sz = (float(v) for v in obs["size"])
    z = sz / 2.0
    pose = f"{_fmt_pose_xy(x, y)} {z:g} 0 0 0"
    return f"""\
    <model name="{name}">
      <static>true</static>
      <pose>{pose}</pose>
      <link name="link">
        <collision name="collision">
          <geometry>
            <box><size>{sx:g} {sy:g} {sz:g}</size></box>
          </geometry>
          <surface>
            <friction><ode/></friction>
            <bounce/>
            <contact/>
          </surface>
        </collision>
        <visual name="visual">
          <geometry>
            <box><size>{sx:g} {sy:g} {sz:g}</size></box>
          </geometry>
          <material>
            <ambient>0.6 0.6 0.7 1</ambient>
            <diffuse>0.6 0.6 0.7 1</diffuse>
            <specular>0.6 0.6 0.7 1</specular>
          </material>
        </visual>
      </link>
    </model>"""


def _build_marker_include(marker: dict[str, Any]) -> str:
    mid = int(marker["id"])
    x = float(marker["x"])
    y = float(marker["y"])
    pose = f"{_fmt_pose_xy(x, y)} {MARKER_SURFACE_Z} 0 0 0"
    return f"""\
    <include>
      <uri>model://aruco_marker_{mid}</uri>
      <name>aruco_marker_{mid}</name>
      <pose>{pose}</pose>
    </include>"""


def build_world_sdf(
    spec: dict[str, Any],
    *,
    relative_spec: str | None = None,
) -> str:
    """Return the full world SDF text for *spec*."""
    validate_spec(spec, check_models=False)
    name = str(spec["name"])
    rel = relative_spec or spec.get("_spec_path") or f"sim/worlds/specs/{name}.yaml"
    parts: list[str] = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        _header_comment(spec, relative_spec=rel),
        '<sdf version="1.9">',
        f'  <world name="{name}">',
        _SKELETON,
    ]
    for obs in spec.get("obstacles") or []:
        parts.append("")
        if obs["type"] == "cylinder":
            parts.append(_build_cylinder_model(obs))
        else:
            parts.append(_build_box_model(obs))
    markers = spec.get("markers") or []
    if markers:
        parts.append("")
        for marker in markers:
            parts.append(_build_marker_include(marker))
    parts.append("  </world>")
    parts.append("</sdf>")
    parts.append("")  # trailing newline
    return "\n".join(parts)


def build_marker_map(
    spec: dict[str, Any],
    *,
    relative_spec: str | None = None,
) -> str:
    """Return the marker map YAML text for *spec* (z always 0.0)."""
    validate_spec(spec, check_models=False)
    name = str(spec["name"])
    rel = relative_spec or spec.get("_spec_path") or f"sim/worlds/specs/{name}.yaml"
    lines = [
        f"# Generated by tools/gen_world.py from {rel}.",
        "# marker_id -> world pose (anchored-ENU, origin = takeoff point). Meters.",
        "markers:",
    ]
    for m in spec.get("markers") or []:
        mid = int(m["id"])
        x = float(m["x"])
        y = float(m["y"])
        lines.append(f"  {mid}: {{x: {x}, y: {y}, z: 0.0}}")
    lines.append("")
    return "\n".join(lines)


def write_outputs(
    spec: dict[str, Any],
    *,
    worlds_dir: Path,
    maps_dir: Path,
    models_dir: Path = DEFAULT_MODELS_DIR,
    relative_spec: str | None = None,
) -> tuple[Path, Path]:
    validate_spec(spec, models_dir=models_dir, check_models=True)
    name = str(spec["name"])
    rel = relative_spec or f"sim/worlds/specs/{name}.yaml"
    world_path = worlds_dir / f"{name}.sdf"
    map_path = maps_dir / f"{name}.yaml"
    worlds_dir.mkdir(parents=True, exist_ok=True)
    maps_dir.mkdir(parents=True, exist_ok=True)
    world_path.write_text(build_world_sdf(spec, relative_spec=rel), encoding="utf-8")
    map_path.write_text(build_marker_map(spec, relative_spec=rel), encoding="utf-8")
    return world_path, map_path


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, required=True, help="Challenge spec YAML path")
    parser.add_argument(
        "--worlds-dir",
        type=Path,
        default=DEFAULT_WORLDS_DIR,
        help="Output directory for world SDF files",
    )
    parser.add_argument(
        "--maps-dir",
        type=Path,
        default=DEFAULT_MAPS_DIR,
        help="Output directory for marker map YAML files",
    )
    parser.add_argument(
        "--models-dir",
        type=Path,
        default=DEFAULT_MODELS_DIR,
        help="Directory of aruco_marker_<id> models",
    )
    args = parser.parse_args(argv)

    spec_path = args.spec.resolve()
    if not spec_path.is_file():
        _usage_error(f"spec not found: {args.spec}")

    try:
        relative_spec = str(spec_path.relative_to(ROOT))
    except ValueError:
        relative_spec = str(args.spec)

    spec = load_spec(spec_path)
    world_path, map_path = write_outputs(
        spec,
        worlds_dir=args.worlds_dir,
        maps_dir=args.maps_dir,
        models_dir=args.models_dir,
        relative_spec=relative_spec,
    )
    print(world_path)
    print(map_path)
    print(
        "rebuild (`just check`) to install the marker map; add a docs/SIM.md row",
        flush=True,
    )


if __name__ == "__main__":
    main()
