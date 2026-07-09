# Plan 043: Competition practice worlds and a committed ArUco marker asset pipeline

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report - do not improvise. When done, update the status row for this plan
> in `plans/README.md` - unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat ead4cc6..HEAD -- sim/ config/markers.yaml tasks.py tools/`
> If `sim/` or `config/markers.yaml` changed, compare the "Current state"
> excerpts before proceeding; on a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2 (direction: competition capability)
- **Effort**: M
- **Risk**: LOW-MED (additive assets; nothing existing changes behavior at speed defaults)
- **Depends on**: none hard. Soft: plans/031-wait-ready-world-aware-physics.md
  (only needed to run NON-default worlds with `--speed != 1.0`; at the default
  speed 1.0 the physics call is skipped entirely, so new worlds work today)
- **Category**: feature
- **Planned at**: commit `ead4cc6`, 2026-07-06

## Why this matters

The repo ships exactly one world: `sim/worlds/default.sdf`, a bare ground
plane with a light. `config/markers.yaml` maps marker 0 to world (8, 0, 0),
but nothing in the world renders there - the vision scenarios work only
because they publish synthetic camera images. For competition prep you want
to fly the actual course shape: a marker field for search missions, a landing
pad for precision landing (plan 042), obstacles for corridor flying, all
visible in the Gazebo GUI and ready for a future camera-equipped model.
Bonus: `tasks.py` already puts `{ROOT}/sim/models` on `GZ_SIM_RESOURCE_PATH`
(lines 503, 820, 915) but the directory does not exist - this plan makes that
path real.

## Current state

- `sim/worlds/default.sdf` - the skeleton to copy: `<world name="default">`,
  `physics type="ode"` with `max_step_size 0.004`, `real_time_factor 1.0`,
  `real_time_update_rate 250`, ground plane, `sunUTC` directional light,
  `spherical_coordinates` block. Keep ALL of these blocks identical in new
  worlds (PX4 SITL's EKF needs the magnetic field + coordinates; the physics
  numbers are flight-verified).
- `sim/models/` - does not exist.
- World selection plumbing (already works, verify, do not modify):
  - `just sim --world <name>` -> `sim_full.launch.py:_world_sdf` (lines
    39-44) prefers `sim/worlds/<name>.sdf` over PX4's worlds.
  - The clock bridge greps `/world/{world}/clock` (lines 83-91), so the SDF's
    `<world name="...">` attribute MUST equal the file stem.
  - `_gz_paths` (lines 47-58) includes `sim/worlds`, PX4 worlds/models, and
    inherits `GZ_SIM_RESOURCE_PATH` from the environment - which `tasks.py`
    seeds with `{ROOT}/sim/worlds:{ROOT}/sim/models`. Models under
    `sim/models/` resolve via `model://<name>` when launched through `just`.
- `config/markers.yaml` (whole file):

```yaml
# marker_id -> world pose (anchored-ENU, origin = takeoff point). Meters.
markers:
  0: {x: 8.0, y: 0.0, z: 0.0}
```

- ArUco parameters that the rendered marker must match
  (`lib/aruco_detector.py`): dictionary `cv2.aruco.DICT_4X4_50`, marker size
  `marker_size_m` default 0.2. Check what `nodes/aruco_pose_publisher.py`
  declares for `marker_size` (a `marker_size` ROS param around its
  `__init__`) and use THAT value as the printed size.
- Synthetic-image caveat: scenarios 05/06 publish their own camera frames;
  they neither need nor see these world assets. Real-camera detection
  additionally needs a camera-bearing vehicle model whose sensor topic
  matches the vision bridge path
  `/world/{world}/model/{model}_0/link/camera_link/sensor/camera/image`
  (`sim_full.launch.py`, vision branch) - that model is OUT of scope here;
  these worlds make the environment side ready and GUI-visible.
- Repo invariant 3: Gazebo worlds and models belong in `sim/worlds` and
  `sim/models`; never edit `PX4_DIR`.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Generate marker textures | `uv run python tools/gen_marker_assets.py` | PNGs + model dirs written, idempotent |
| SDF validity | `gz sdf -k sim/worlds/<name>.sdf` (ROS/gz shell) | `Check complete` / exit 0 |
| Full gate | `just check` | exit 0 |
| Live boot (operator) | `just sim --world marker_field --gui` | READY verdict; markers visible |

## Scope

**In scope**:
- `tools/gen_marker_assets.py` (create; generator script)
- `sim/models/aruco_marker_{0,1,2}/` (create; generated, committed)
- `sim/worlds/marker_field.sdf`, `sim/worlds/landing_pad.sdf`,
  `sim/worlds/obstacle_course.sdf` (create)
- `config/markers.yaml` (add markers 1 and 2 for the field world)
- `sim/launch/sim_full.launch.py` (ONLY the `_gz_paths` list: add
  `str(project_root / "sim" / "models")` so direct `ros2 launch` matches
  `just sim`)
- `README.md`/`AGENTS.md` NOT touched; document worlds in a short header
  comment inside each SDF instead

**Out of scope**:
- A camera-equipped vehicle model (needs bridge-topic alignment; future work).
- Editing `default.sdf` or anything under `PX4_DIR`.
- `tools/wait_ready.py` (plan 031 owns the world-aware physics call).
- Scenario changes; 05/06 stay synthetic.

## Git workflow

- Branch: `advisor/043-competition-worlds`
- Commit style: `feat(sim): competition worlds (marker field, landing pad, obstacles) + generated ArUco assets`
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: `tools/gen_marker_assets.py`

A small script (typer optional; plain `main()` fine - match the style of
other `tools/*.py`) that, for marker ids `(0, 1, 2)`:

1. Renders the marker bitmap:
   `cv2.aruco.generateImageMarker(cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50), marker_id, 512)`
   and adds a white quiet-zone border (pad to ~615 px so the border is ~10%
   per side - detection needs the quiet zone).
2. Writes `sim/models/aruco_marker_<id>/materials/textures/aruco_marker_<id>.png`.
3. Writes `model.config` (name, sdf version, author placeholder) and
   `model.sdf`: a `<static>true</static>` model with a single link, a thin
   box visual `<size>S S 0.01</size>` where `S` is the marker size in meters
   (read the default from `aruco_pose_publisher`'s `marker_size` param -
   verify in code; expected 0.2, but if competitions need visibility from 3 m
   altitude a 0.5 m printed size with a matching `marker_size` param note is
   acceptable - pick ONE size, state it in the model.config description, and
   note in the SDF header that `marker_size` must match), with a PBR material:

```xml
<material>
  <diffuse>1 1 1 1</diffuse>
  <pbr><metal>
    <albedo_map>model://aruco_marker_<id>/materials/textures/aruco_marker_<id>.png</albedo_map>
  </metal></pbr>
</material>
```

   No collision element (flat decal; the ground plane provides physics).
4. Idempotent: re-running overwrites byte-identically (fix any timestamp
   nondeterminism; PNG encoding of the same array is deterministic).

Run it and COMMIT the generated files (the script is the provenance; CI/dev
machines must not need to regenerate).

**Verify**: `uv run python tools/gen_marker_assets.py` twice ->
`git status` identical after both runs; `ls sim/models/aruco_marker_0/materials/textures/` shows the PNG.

### Step 2: Three worlds

Copy `sim/worlds/default.sdf` and for each: change ONLY the
`<world name="...">` attribute (must equal the file stem), add a 2-4 line
header comment (purpose, marker layout, which mission/scenario uses it), and
add content models. Keep physics/light/coordinates/ground blocks identical.

1. `marker_field.sdf`: include the three markers at poses that
   `config/markers.yaml` will mirror:

```xml
<include><uri>model://aruco_marker_0</uri><pose>8 0 0.005 0 0 0</pose></include>
<include><uri>model://aruco_marker_1</uri><pose>-6 10 0.005 0 0 0</pose></include>
<include><uri>model://aruco_marker_2</uri><pose>0 -12 0.005 0 0 0</pose></include>
```

2. `landing_pad.sdf`: a 1.5 m radius static grey cylinder (height 0.02) at
   (8, 0, 0) as the pad, with `model://aruco_marker_0` at
   `8 0 0.03` on top - matches plan 042's `precision_land.yaml` approach
   waypoint and marker 0's mapped pose.
3. `obstacle_course.sdf`: `model://aruco_marker_0` at (8, 0, 0.005) plus 4-6
   static box/cylinder obstacles (e.g. 1x1x4 m pillars) forming a slalom
   between origin and the marker, all clear of the direct climb column at
   (0,0). Inline `<model>` definitions with simple geometry are fine here
   (they are world-specific, not reusable assets).

Gazebo pose convention note for the header comments: SDF world poses here are
ENU-compatible (world_frame_orientation ENU in the spherical_coordinates
block), matching `config/markers.yaml` anchored-ENU when the vehicle spawns
at origin - state this in each header.

**Verify**: in a gz-capable shell (distrobox):
`gz sdf -k sim/worlds/marker_field.sdf && gz sdf -k sim/worlds/landing_pad.sdf && gz sdf -k sim/worlds/obstacle_course.sdf` -> all pass

### Step 3: Align `config/markers.yaml`

```yaml
# marker_id -> world pose (anchored-ENU, origin = takeoff point). Meters.
# Must mirror the marker <include> poses in sim/worlds/*.sdf.
markers:
  0: {x: 8.0, y: 0.0, z: 0.0}
  1: {x: -6.0, y: 10.0, z: 0.0}
  2: {x: 0.0, y: -12.0, z: 0.0}
```

(Existing consumer: `marker_localizer` relocalization - adding ids is
additive; id 0 is unchanged so scenarios 05/06 are unaffected.)

**Verify**: `uv run pytest tests/unit -q` -> no failures (if any test pins
the markers file content, reconcile it - check `rg -l "markers.yaml" tests/`)

### Step 4: `_gz_paths` includes `sim/models`

In `sim/launch/sim_full.launch.py:_gz_paths`, add
`str(project_root / "sim" / "models"),` after the `sim/worlds` entry. This
makes direct `ros2 launch` resolve `model://aruco_marker_*` the same way
`just sim` (which injects it via `GZ_SIM_RESOURCE_PATH`) already would.

**Verify**: `uv run ruff check sim/launch/sim_full.launch.py` -> exit 0

### Step 5: Full gate + live boot (operator-gated)

1. `just check` -> exit 0.
2. Operator: `just sim --world marker_field --gui` -> READY verdict; three
   markers visible on the ground in the GUI. `just stop`.
3. Operator: `just sim --world landing_pad` (headless is fine) -> READY;
   `rg "world.*landing_pad|marker" logs/latest.log | head` shows the world
   loaded without model-resolution errors
   (`rg -i "unable to find\|error" logs/latest.log` -> no model URI errors).
   `just stop`.
4. Regression: `just sim` (default world) -> READY. `just stop`.

If you cannot run a sim, complete steps 1-4, run the `gz sdf -k` checks, and
STOP reporting live verification pending.

## Test plan

`gz sdf -k` on all three worlds (machine check), generator idempotency
(Step 1), the existing unit suite for markers.yaml consumers, and the
operator boot checks (READY verdict is itself a post-condition check: clock
bridge up means the world name matched the file stem).

## Done criteria

- [ ] `uv run python tools/gen_marker_assets.py` is idempotent; assets committed
- [ ] `gz sdf -k` passes on all three new worlds
- [ ] `rg -n "<world name" sim/worlds/*.sdf` -> each name equals its file stem
- [ ] `config/markers.yaml` mirrors the marker_field poses; id 0 unchanged
- [ ] `just check` exits 0
- [ ] Live: default + marker_field + landing_pad boot READY (or reported as pending operator sign-off)
- [ ] `git status` shows only in-scope files added/modified
- [ ] `plans/README.md` status row updated

## STOP conditions

- `gz sdf -k` unavailable or failing on the COPIED skeleton itself (gz
  version drift - report the gz version).
- A world boots but the clock bridge never comes up (verdict NOT READY,
  `rg clock_bridge logs/latest.log` shows the wait loop spinning) - the world
  name/stem contract broke; fix the name attribute, do not patch the bridge.
- PX4 SITL fails to spawn the vehicle in a new world (`rg src=px4 logs/latest.log`
  shows spawn errors) - likely a physics-block divergence; diff against
  `default.sdf` and report if the skeleton was kept identical.
- Anything requires editing files under `PX4_DIR` (invariant 3; also the
  no-PX4/Gazebo-modification rule) - STOP.

## Maintenance notes

- Real-camera vision practice needs a vehicle model with a `camera_link`
  sensor whose topic path matches the bridge template in
  `sim_full.launch.py`; when that lands, these worlds are already the test
  environments (markers physically present).
- New marker ids: extend the id tuple in `tools/gen_marker_assets.py`, rerun,
  add the world include + `config/markers.yaml` row - keep all three in sync.
- Reviewer: confirm marker PNGs have a white quiet zone (a borderless marker
  will not detect) and that committed binaries are small (512-ish px, tens of
  KB each).
