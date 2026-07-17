# Plan 062: Camera perception spike — real pixels to ArUco detections in sim (design/spike, not build-everything)

> **Executor instructions**: This is a SPIKE plan: the deliverable is a
> working proof-of-concept on a branch plus a short design writeup
> (`docs/superpowers/` is NOT the home — write `plans/062-findings.md`), not
> polished product code. Follow the steps, verify each, and STOP where told.
> When done, update `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 01f94c7..HEAD -- sim/ vehicles/ src/core/ros_px4_template_core/nodes/aruco_pose_publisher.py src/core/ros_px4_template_core/lib/aruco_detector.py docs/SIM.md`
> On any mismatch with the excerpts below, STOP.
>
> **Requires a live sim environment AND plan 049 merged** (repo worlds must boot).

## Status

- **Priority**: P1 (direction — the keystone gap)
- **Effort**: L (spike scoped to ~a day; productization is a follow-up plan)
- **Risk**: MED (camera rendering cost, model-vs-PX4-airframe compatibility)
- **Depends on**: plans/049-unblock-repo-worlds.md (hard)
- **Category**: direction
- **Planned at**: commit `01f94c7`, 2026-07-10

## Why this matters

Every vision capability in the registry (`aruco_hover`, `search_relocalize`,
`precision_land`) runs on **fabricated detections** — `docs/SIM.md:36-43`
says so explicitly: the stock x500 has no camera, so `--vision aruco` bridges
nothing and scenarios inject synthetic `MarkerDetection`s. The mission FSM is
proven; the perception half (dictionary, marker size, intrinsics, motion
blur, lighting) has never seen a rendered pixel. Last year's competition
stack validated its ENTIRE perception pipeline in sim against a real camera
model (`raytheon-2026/launch_scripts/full_system.sh:26` spawns
`PX4_GZ_MODEL=x500_mono_cam_down`; `src/aruco_detection/aruco_detection/`
`aruco_detector_sim.py:51` subscribes to the Gazebo camera topic and runs
`cv2.aruco.detectMarkers` on rendered frames). A team on this template today
would meet real pixels for the first time at the field.

The supply side is closer than it looks — the plumbing already exists:

- `sim_full.launch.py:141-169` (`_vision_bridge`) already bridges
  `/world/<w>/model/<model>_0/link/camera_link/sensor/camera/image` (+
  `camera_info`) to `/camera/image_raw` / `/camera/camera_info` when
  `--vision aruco` — it just never fires because the stock x500 publishes no
  such topic.
- `nodes/aruco_pose_publisher.py` already consumes `/camera/image_raw` +
  `/camera/camera_info`, runs `lib/aruco_detector.detect_markers` (solvePnP,
  DICT_4X4_50, `marker_size_m=0.2`), maps camera→body FLU
  (`camera_to_body`, nadir extrinsic at `:96-99`), and publishes
  `/drone/marker_detection`.
- Plan 043 shipped marker worlds whose markers are generated at the matching
  0.2 m code size (`docs/SIM.md` "Marker scale") with `tools/gen_marker_assets.py`.

The missing piece is ONE artifact: a camera-equipped vehicle model whose
sensor topic matches what `_vision_bridge` expects — plus proof the pipeline
holds end to end.

## Spike questions (what this plan must answer)

1. Can a camera-equipped x500 variant live in `sim/models/` (never in
   `PX4_DIR`) and still be spawned by PX4's `gz_bridge`
   (`PX4_SIM_MODEL=gz_<model>`)? PX4 resolves models via
   `GZ_SIM_RESOURCE_PATH`, which our launch already populates with
   `sim/models` (`sim_full.launch.py:47-59`) and PX4's `gz_env.sh` APPENDS to
   rather than clobbers — so in principle yes; prove it.
2. Does the rendered ArUco detection land within tolerance? (Detection of
   marker id 0 at known world position, FLU offset error < 0.15 m at 3 m
   altitude.)
3. What does camera rendering cost? (Headless sim with camera: boot time and
   real-time factor vs. baseline.)
4. Does the existing `05_aruco_hover` scenario pass with REAL detections
   replacing the synthetic overlay?

## Current state (key excerpts)

- The model dir pattern to copy: `sim/models/aruco_marker_0/{model.config,model.sdf}`
  (plan 043's marker models). A vehicle model is bigger; the reference for a
  camera-bearing x500 is PX4's own `x500_mono_cam` family under
  `<PX4_DIR>/Tools/simulation/gz/models/` — read it there (read-only) and
  note that PX4 model SDFs `<include>` the base `x500` plus a camera link.
  A repo-local variant can do the same include (the base x500 resolves from
  PX4's model path via `GZ_SIM_RESOURCE_PATH`).
- `_vision_bridge` topic template (must match your model's link/sensor names
  exactly): `/world/{world}/model/{model}_0/link/camera_link/sensor/camera/image`.
- Launch model arg: `just sim --model <name>` → `PX4_SIM_MODEL="gz_${SIM_MODEL}"`
  (`_start_gz_px4.sh:67`). PX4 requires an airframe config named
  `gz_<model>`; PX4 ships airframes only for its own model names — **this is
  the spike's main unknown**: whether `PX4_SIM_MODEL=gz_x500` can be combined
  with a differently-named repo model, or whether the repo model must be
  named so an existing PX4 airframe matches (e.g. reuse the
  `x500_mono_cam` airframe name if PX4 v1.17 ships one — check
  `<PX4_DIR>/ROMFS/px4fmu_common/init.d-posix/airframes/` read-only).
- Synthetic path to keep: scenarios 05/06 fabricate detections by publishing
  to `/drone/marker_detection` — grep `tests/scenarios/05_aruco_hover.py` for
  the publisher. The spike must NOT break the synthetic path (it stays the
  fast non-rendering tier).

## Commands you will need

| Purpose | Command | Expected |
|---------|---------|----------|
| Boot with camera | `just sim --world marker_field --model <cam_model> --vision aruco` | READY |
| Camera topic live | `gz topic -l \| grep camera` then `ros2 topic hz /camera/image_raw` | >5 Hz |
| Detection live | `ros2 topic echo /drone/marker_detection --once` | `valid: true`, plausible FLU offset |
| Baseline timing | `time just sim` (before/after comparison) | recorded numbers |
| Quality gate | `just check` | exit 0 |

## Scope

**In scope** (spike branch):
- `sim/models/<cam_model>/` (new model SDF + config)
- `vehicles/` or `sim/` config touch-ups strictly needed to spawn it
- `plans/062-findings.md` — the writeup (answers to the 4 questions, numbers,
  and the recommended productization slice)
- OPTIONALLY (only if questions 1-2 answer cleanly and time remains): a
  variant run of scenario 05 against real detections, as evidence — not a
  committed scenario change

**Out of scope**:
- Anything under `PX4_DIR` (read-only reference only)
- Committing changes to scenarios 05/06/08 or `capabilities.toml` (that is
  the productization follow-up, planned after the spike's findings)
- Camera intrinsics tuning, obstacle mapping (DIR-04), moving markers (DIR-02)
- `marker_localizer` / relocalization changes

## Git workflow

- Branch: `advisor/062-camera-spike` (expected to merge only the model +
  findings doc; anything else stays on the branch as evidence)
- Commit style: `feat(sim): camera-equipped x500 variant (perception spike)`

## Steps

### Step 1: Read PX4's camera model + airframe inventory (read-only)

List `<PX4_DIR>/Tools/simulation/gz/models/ | grep -i cam` and
`<PX4_DIR>/ROMFS/px4fmu_common/init.d-posix/airframes/ | grep -i cam`.
Record: exact model names, their camera link/sensor naming, and which have
matching `gz_*` airframes in this PX4 checkout.

**Verify**: findings noted in `plans/062-findings.md` (start the file now).

### Step 2: Repo-local camera model

Create `sim/models/x500_cam_down/` that `<include>`s the PX4 base model your
Step 1 inventory supports, adding a nadir camera on link `camera_link`,
sensor name `camera` (to match `_vision_bridge`'s topic template), modest
resolution (640x480 @ 15-20 Hz — competition-realistic and cheap to render),
and `<always_on>`/`<update_rate>` set. Copy the camera sensor block from
PX4's own mono_cam model, adjusting names.

Airframe pairing per Step 1's finding: if PX4 v1.17 ships
`gz_x500_mono_cam`, the least-risk path is naming the repo model
`x500_mono_cam` so `PX4_SIM_MODEL=gz_x500_mono_cam` resolves BOTH the
airframe (PX4's) and the model (ours wins if `GZ_SIM_RESOURCE_PATH` puts
`sim/models` first — confirm ordering in `_gz_paths`, `sim_full.launch.py:47-59`:
repo paths ARE first). Record which pairing worked.

**Verify**: `just sim --world marker_field --model x500_mono_cam --vision aruco`
(adjust name) → READY, and `gz topic -l | grep camera/image` → the topic
exists. If the model fails to spawn, capture `rg src=px4 logs/latest.log` and
iterate ONCE on naming; then STOP condition 1.

### Step 3: Pixels → detection

With the sim up, position the vehicle over marker 0 (marker_field places id 0
at ENU `(8, 0, 0.005)` — fly there via `just sim --overlay auto_arm` plus the
demo path, or simplest: use a world where the marker is at the origin —
generate a one-off world variant if needed, `tools/gen_marker_assets.py`
shows how markers are placed).

**Verify**: `ros2 topic hz /camera/image_raw` ≥ 5 Hz;
`ros2 topic echo /drone/marker_detection --once` → `valid: true`, `id: 0`,
FLU offset magnitude consistent with the vehicle-marker geometry (±0.15 m at
3 m altitude). Record actual error + rate in the findings doc.

### Step 4: Cost + regression numbers

- `time just sim` (default world, no camera) vs.
  `time just sim --world marker_field --model <cam> --vision aruco` — record
  boot deltas.
- With the camera sim up for 60 s: `gz stats` (or the RTF line in logs) —
  record real-time factor.
- `just test e2e` on the branch → all PASS (proves the synthetic tier and the
  default model are untouched).

### Step 5: Findings + recommended slice

Complete `plans/062-findings.md`: answers to the four spike questions with
numbers; the exact model/airframe pairing that worked; and a recommended
productization slice (expected shape: promote scenario 05 to real detections
behind its `sim_vision` config, add a `sim_model` field to
`capabilities.toml`, wire `docs/SIM.md` + TOPICS vision rows — but let the
spike results dictate). Update the plans index row with a one-line verdict.

## Done criteria

- [ ] Camera model in `sim/models/`, spawned by PX4, publishing bridged `/camera/image_raw`
- [ ] Real `MarkerDetection` with `valid: true` and offset error recorded (<0.15 m target; record actual)
- [ ] Boot-time and RTF numbers recorded in `plans/062-findings.md`
- [ ] `just check` exit 0 and `just test e2e` all PASS on the branch
- [ ] `plans/README.md` row updated with the spike verdict

## STOP conditions

1. No PX4 v1.17 airframe pairs with any camera model naming (Step 1/2 dead
   end) — the alternative (committing a custom airframe file) touches
   PX4_DIR and is forbidden; report what PX4 ships and stop.
2. Camera rendering forces headless RTF below ~0.7 — the perception tier
   would be too slow for e2e; record numbers and stop (the finding itself is
   the deliverable).
3. Detections are wildly wrong (>0.5 m at 3 m altitude) after checking
   `marker_size_m` (0.2 — code size, NOT the 0.25 m printed surface, see
   docs/SIM.md "Marker scale") and the nadir extrinsic — report with a saved
   camera frame.

## Maintenance notes

- Productization follow-up (next improve round): real-detection variants of
  scenarios 05/08, `sim_model` in capabilities.toml, and possibly a
  moving-marker actor (rejected-for-now DIR-02 becomes cheap after this).
- The synthetic detection path must stay: it is the fast tier (no rendering)
  and the only path for `--world default`.
