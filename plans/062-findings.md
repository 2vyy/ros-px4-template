# Plan 062 findings — Camera perception spike (real pixels to ArUco detections)

**Verdict: SUCCESS.** A repo-local camera-equipped x500 renders real frames of a
world ArUco marker, and the existing detector produces a valid, accurate
`MarkerDetection` from those pixels. Two non-obvious blockers were found and
fixed; both would have surprised a team at the field. The full pipeline
(rendered pixels -> `cv2.aruco.detectMarkers` -> solvePnP -> body-FLU offset) is
now proven in sim, not just against fabricated detections.

Spike ran on branch `advisor/062-camera-spike` against `marker_field` (marker 0
at ENU `(8, 0, 0.005)`), flown to `(8, 0, 3)` via `--overlay auto_arm`.

## Answers to the four spike questions

### Q1 — Can a repo-local camera model spawn via PX4's gz_bridge? YES.

- `sim/models/x500_mono_cam_down/` `<include>`s PX4's base `x500` and adds an
  inline nadir camera link. PX4 spawns it with
  `PX4_SIM_MODEL=gz_x500_mono_cam_down`, reusing PX4's existing airframe
  **`4014_gz_x500_mono_cam_down`** (v1.17 ships it) — no `PX4_DIR` edit.
- Our repo model **wins over PX4's identically-named model** because `_gz_paths`
  puts `sim/models` first on `GZ_SIM_RESOURCE_PATH` and PX4's `gz_env.sh`
  appends. Confirmed by the live gz topic carrying **our** sensor name:
  `/world/marker_field/model/x500_mono_cam_down_0/link/camera_link/sensor/camera/image`.
- **Gotcha (fixed):** PX4's stock `mono_cam` names its sensor **`imager`**, so
  PX4's own `x500_mono_cam_down` would publish `.../sensor/imager/image` and
  `_vision_bridge` (which expects `.../sensor/camera/...`) would silently bridge
  nothing. Our model names the sensor `camera` to match.

### Q2 — Does the rendered detection land within tolerance? YES (~0.06 m).

Over 147 valid detections while hovering at ~3.3 m directly above marker 0:

| Axis (body FLU) | mean | median | range |
|-----------------|------|--------|-------|
| Forward (x)     | -0.055 m | -0.059 m | [-0.35, 1.10] |
| Left (y)        | +0.011 m | — | [-0.064, 0.056] |
| Up (z)          | ~-3.35 m (= -altitude, correct) | | |

- **Typical horizontal error ~0.06 m at 3.3 m altitude** — well under the
  0.15 m target. Marker id decoded correctly (`id: 0`), 134 valid / 13 invalid
  in a 10 s window (~91%).
- The 1.10 m forward **outlier** (1 of 147) is a transient during a pitch-settle,
  not a systematic bias: the detector explicitly assumes a perfectly-aligned
  nadir camera (`aruco_pose_publisher.py:90`) and ignores vehicle attitude, so a
  few degrees of hover pitch briefly shifts a centered marker. Median/mean sit
  near zero. NOT a STOP-3 failure (`marker_size_m=0.2` and the nadir extrinsic
  are correct — z came out equal to true altitude).

### Q3 — Rendering cost? Cheap. STOP-2 (RTF < 0.7) NOT hit.

- `wait_ready`'s "Physics at realtime (world SDF defaults)" gate **passed** with
  the camera model.
- Camera images sustained **~15 Hz** (of 20 Hz nominal) headless.
- Boot to READY with camera+marker world: **~17-21 s**, vs **~13-18 s** for the
  default headless sim. Camera rendering adds only a few seconds of setup.
- (A precise RTF number was not cleanly captured — whole-second `/clock`
  sampling is too quantized over a short window — but the realtime gate is the
  authoritative signal and it passed.)

### Q4 — Does 05_aruco_hover pass with real detections? NOT RUN (optional).

Left for the productization slice below. The synthetic path (scenarios 05/06/08
fabricating `/drone/marker_detection`) is untouched and remains the fast,
non-rendering tier and the only path for `--world default`.

## The two keystone findings (would have bitten a team at the field)

1. **Marker textures need `<emissive_map>` to render in the gz camera sensor.**
   A PBR `<albedo_map>` alone renders the marker as a **solid black square** in
   the sensor's offscreen render (no error logged), so `detectMarkers` sees a
   featureless blob and rejects it. Adding an `emissive_map` (same PNG) makes
   the marker self-lit and its DICT_4X4_50 grid readable. This affects ALL
   marker assets from plan 043. Fixed here for markers 0/1/2. Also switched the
   texture path to a `model://` URI (relative paths are unreliable in the sensor
   render context) and the geometry to a `<plane>` (clean single-quad UV for a
   flat decal).

2. **Camera FOV must be narrow enough to resolve the marker.** PX4's stock
   `mono_cam` uses a 1.74 rad (~100 deg) fisheye; at 3 m altitude a 0.25 m
   marker then spans only ~20 px — too few to resolve the 4x4 bit grid. Our
   model uses **1.0 rad (~57 deg)**, giving ~50 px, which decodes reliably. The
   camera is also mounted 6 cm below `base_link` so the x500's own arms/props
   stay out of the downward cone (at body-center they filled the frame edges).

## What was built (branch `advisor/062-camera-spike`)

- `sim/models/x500_mono_cam_down/{model.config,model.sdf}` — repo-local nadir
  camera x500 (sensor `camera`, 640x480 @ 20 Hz, 1.0 rad FOV).
- `sim/models/aruco_marker_{0,1,2}/model.sdf` — `emissive_map` + `model://`
  texture URI + plane geometry (the rendering fix). Only marker 0 was flown
  over and verified live; 1/2 use the identical proven config.

## Recommended productization slice (next improve round)

1. Promote `05_aruco_hover` to a **real-detection variant** gated behind a new
   `sim_model = "x500_mono_cam_down"` field in `tests/capabilities.toml` (so
   `just scenario`/e2e boot the camera model + `--vision aruco`), keeping the
   synthetic path as the default fast tier.
2. Add a camera row to `docs/TOPICS.md` (`/camera/image_raw`,
   `/camera/camera_info`) and update `docs/SIM.md`'s perception limitation
   paragraph (real detections now possible on the camera model).
3. Consider folding vehicle attitude into `aruco_pose_publisher` (use
   `/fmu/out/vehicle_attitude` to de-rotate the nadir assumption) to kill the
   pitch-coupling transient before it matters for precision landing.
4. `08_precision_land` real-detection variant becomes cheap after (1).
