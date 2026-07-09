# Plan 043: Add deterministic competition worlds and correctly scaled ArUco assets

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving on. If a
> STOP condition occurs, stop and report. Do not improvise. When done, update
> this plan's row in `plans/README.md` unless a reviewer owns the index.
>
> **Drift check (run first)**:
> `git diff --stat e05d19b..HEAD -- tools/gen_marker_assets.py sim/models sim/worlds sim/launch/sim_full.launch.py config/marker_maps src/core/setup.py tests/unit/test_marker_assets.py docs/SIM.md README.md`
>
> Also run `git diff --stat -- <the same paths>` to expose uncommitted work.
> Plan 031 already changed world-aware readiness and is DONE. Stop on any
> other semantic mismatch.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: LOW-MED (additive simulation assets plus package resources)
- **Depends on**: none; plan 031 is already DONE
- **Category**: direction
- **Planned at**: commit `e05d19b`, 2026-07-09

## Why this matters

The template has one empty world and a marker map whose marker is not rendered.
Synthetic scenarios verify perception logic, but they do not provide a course
for GUI inspection, flight rehearsal, or future camera-equipped models. This
plan adds deterministic marker, landing, and obstacle worlds without changing
the default world or claiming real-camera E2E support that the current x500
model does not provide.

## Current state

- `sim/worlds/default.sdf` contains the flight-verified physics, ground,
  magnetic field, light, and ENU spherical coordinates.
- `sim/models/` does not exist.
- `sim_full.py:_world_sdf` prefers repository worlds; `_gz_paths` includes
  repository worlds but not repository models.
- `tasks.py` already seeds `sim/models` in `GZ_SIM_RESOURCE_PATH` for normal
  `just sim` launches.
- `aruco_pose_publisher.py:41-45` uses DICT_4X4_50 and a 0.2 m marker code size.
- `marker_localizer.py:43` accepts a `marker_map_file` parameter.
- `config/markers.yaml` is the installed default map used by existing
  synthetic scenarios. It must remain unchanged.
- The current x500 camera topic expected by `_vision_bridge` is not produced
  by the stock model. Physical markers are therefore GUI/manual assets in this
  plan, not an automated perception capability.

## Design decisions

### Physical scale

OpenCV's `marker_size_m=0.2` describes the black ArUco code, not the padded
texture. Generate a 512 px code with a 64 px white quiet zone on every side,
making a 640 px texture. The rendered surface side is therefore:

`0.2 m * 640 / 512 = 0.25 m`

This preserves a 0.2 m black code and prevents the roughly 20 percent range
error caused by fitting the padded texture onto a 0.2 m surface.

### World-specific maps

Keep `config/markers.yaml` unchanged for existing scenarios. Put the
three-marker field map in `config/marker_maps/marker_field.yaml`. A marker map
must describe the selected world, not every marker that might exist in any
world.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Generator tests | `uv run pytest tests/unit/test_marker_assets.py -q` | all pass |
| Generate assets | `uv run python tools/gen_marker_assets.py` | deterministic model trees written |
| SDF validation | `gz sdf -k sim/worlds/<world>.sdf` | exit 0 for all worlds |
| Full gate | `just check` | exit 0 |
| Live boot | `just sim --world marker_field --gui` | READY; assets visible |

## Scope

**In scope**:

- `tools/gen_marker_assets.py` (create)
- `tests/unit/test_marker_assets.py` (create)
- `sim/models/aruco_marker_{0,1,2}/` (generated and committed)
- `sim/worlds/marker_field.sdf` (create)
- `sim/worlds/landing_pad.sdf` (create)
- `sim/worlds/obstacle_course.sdf` (create)
- `config/marker_maps/marker_field.yaml` (create)
- `sim/launch/sim_full.launch.py` (`_gz_paths` only)
- `src/core/setup.py` (install world-specific marker maps)
- `docs/SIM.md` (create), `README.md` (one link/table)
- `plans/README.md` status only

**Out of scope**:

- Modifying `config/markers.yaml` or existing scenarios.
- A camera-equipped vehicle model or new Gazebo-to-ROS camera bridge.
- Automated physical-marker detection or precision-landing verification.
- Capability metadata changes such as `sim_world`.
- Editing `default.sdf`, `tools/wait_ready.py`, or anything under `PX4_DIR`.

## Git workflow

- Branch: `advisor/043-competition-worlds`
- Commit: `feat(sim): add competition worlds and ArUco assets`
- Do not push or open a PR without operator instruction.

## Steps

### Step 1: Build a testable deterministic generator

Create `tools/gen_marker_assets.py` with constants:

- dictionary: `DICT_4X4_50`
- IDs: `(0, 1, 2)`
- code pixels: 512
- quiet zone: 64 px per side
- code size: 0.2 m
- surface size: 0.25 m, derived from the pixel ratio

Separate pure rendering/text functions from filesystem output. `main()` writes
to repository `sim/models`; tests must be able to pass a temporary output root.

For each ID write:

- `materials/textures/aruco_marker_<id>.png` with a pure white border;
- deterministic `model.config` describing the 0.2 m code and 0.25 m surface;
- deterministic `model.sdf` for a static, collision-free, 0.01 m thin box
  whose top texture uses the generated PNG.

Do not include timestamps, host paths, or nondeterministic metadata.

Tests must verify image dimensions, 64 px white border, non-white code area,
surface/code size constants, expected model URI, and byte-identical output
from two runs into the same temporary directory.

**Verify**: `uv run pytest tests/unit/test_marker_assets.py -q` -> all pass.

### Step 2: Generate and inspect committed assets

Run the generator twice. The second run must produce no diff. Inspect each PNG
and model file, then commit the generated files with the generator.

**Verify**:

- `uv run python tools/gen_marker_assets.py` twice -> second run leaves
  `git diff --exit-code -- sim/models` unchanged relative to the first run.
- Each texture is 640 by 640 and each model declares a 0.25 m surface.

### Step 3: Add three worlds from the verified default skeleton

Copy the default world blocks without changing physics, gravity, magnetic
field, ground, light, or spherical coordinates. The `<world name>` must match
the filename stem.

- `marker_field.sdf`: marker 0 at `(8, 0, 0.005)`, marker 1 at
  `(-6, 10, 0.005)`, marker 2 at `(0, -12, 0.005)`.
- `landing_pad.sdf`: a static grey 1.5 m radius, 0.02 m high cylinder centered
  at `(8, 0)` with marker 0 just above its top surface.
- `obstacle_course.sdf`: marker 0 at `(8, 0)` plus four to six static obstacles
  forming a slalom while leaving the origin climb column clear.

Each file gets a short header documenting purpose, marker layout, and anchored
ENU coordinates. Models must not introduce collisions on the marker decal
itself; the landing pad and obstacles do have appropriate collisions.

**Verify**: run `gz sdf -k` separately on all three files -> each exits 0.

### Step 4: Add the world-specific marker map

Create `config/marker_maps/marker_field.yaml` matching the three field poses.
Do not edit `config/markers.yaml`.

Update `src/core/setup.py` to install `config/marker_maps/*.yaml` under the
package share directory. Extend the existing package/resource test pattern so
the new map is verified after a build.

**Verify**: `uv run pytest tests/unit/test_package_xml.py tests/unit/test_marker_map.py -q`
-> all pass; after `just check`, the installed marker-field map exists under
`install/ros_px4_template_core/share/ros_px4_template_core/config/marker_maps/`.

### Step 5: Make direct ROS launch resolve repository models

Add `str(project_root / "sim" / "models")` immediately after repository
worlds in `_gz_paths`. Do not change `_world_sdf`, bridge topics, or PX4 paths.

**Verify**: `uv run ruff check sim/launch/sim_full.launch.py` -> exit 0.

### Step 6: Document honest usage and limitations

Create `docs/SIM.md` with a terse table for `default`, `marker_field`,
`landing_pad`, and `obstacle_course`, including marker coordinates and example
`just sim --world ...` commands. Explain:

- marker code size is 0.2 m despite the 0.25 m padded surface;
- `marker_field.yaml` must be selected when localizing IDs 1 and 2;
- stock x500 has no bridged camera, so physical assets are currently GUI and
  manual flight practice only;
- scenarios 05/06 remain synthetic by design.

Add one README link to `docs/SIM.md`.

**Verify**: `uv run python tools/check_docs.py` -> pass.

### Step 7: Run full and live verification

1. `just check` -> exit 0.
2. `just sim --world marker_field --gui` -> READY; inspect all three IDs and
   white quiet zones; `just stop`.
3. `just sim --world landing_pad` -> READY with no model-resolution error;
   `just stop`.
4. `just sim --world obstacle_course` -> READY; `just stop`.
5. `just sim` -> default world READY; `just stop`.

If GUI inspection is unavailable, do not mark DONE. Report SDF and headless
boot results plus the pending visual sign-off.

## Test plan

- Deterministic generator unit tests in a temporary directory.
- Exact quiet-zone and physical-scale assertions.
- `gz sdf -k` for every new world.
- Package-resource check for the field map.
- Live boot of all new worlds and default regression.
- GUI inspection of marker IDs and border visibility.

## Done criteria

- [ ] Generator is deterministic and unit-tested.
- [ ] Black code is 0.2 m; padded surface is 0.25 m.
- [ ] `config/markers.yaml` is unchanged.
- [ ] Field map exactly matches `marker_field.sdf`.
- [ ] All SDF files validate and world names match filename stems.
- [ ] `just check` exits 0.
- [ ] All three worlds and default boot READY.
- [ ] GUI sign-off confirms markers render with white quiet zones.
- [ ] Only in-scope files changed; the plan index row is updated.

## STOP conditions

- The copied default skeleton fails `gz sdf -k` before new models are added.
- The generated texture maps to a face/orientation that is not visible from
  above. Report the rendered result; do not change camera conventions.
- Any implementation requires modifying `PX4_DIR`.
- A new world breaks clock readiness because world name and stem differ.
- The work expands into a camera-equipped model or automated scenario.

## Maintenance notes

- New marker IDs require generator output, the relevant world include, and
  the matching world-specific map.
- A later camera-model plan can turn these environments into true perception
  scenarios without changing their geometry.
- Plan 042 may use `landing_pad` for manual observation, but its automated
  acceptance remains synthetic and does not depend on this plan.
