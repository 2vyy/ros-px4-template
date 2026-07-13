# Simulation worlds

Deterministic worlds for GUI inspection and manual flight practice, generated
by `tools/gen_marker_assets.py` (ArUco markers) and hand-written from the
flight-verified `default.sdf` skeleton (physics, gravity, magnetic field,
ground, light, spherical coordinates).

| World | `just sim --world ...` | Marker IDs (anchored-ENU) | Notes |
|-------|-------------------------|---------------------------|-------|
| `default` | `just sim` | none | Flight-verified baseline; unchanged. |
| `marker_field` | `just sim --world marker_field --gui` | 0: `(8, 0, 0.005)`, 1: `(-6, 10, 0.005)`, 2: `(0, -12, 0.005)` | Select `config/marker_maps/marker_field.yaml` (not `config/markers.yaml`) to localize IDs 1 and 2. |
| `landing_pad` | `just sim --world landing_pad` | 0: `(8, 0, 0.025)`, just above the 1.5 m radius pad top | Uses the unmodified `config/markers.yaml` (marker 0 only); existing precision-landing scenarios keep working. |
| `obstacle_course` | `just sim --world obstacle_course` | 0: `(8, 0, 0.005)` | Five static slalom pylons between the origin and the marker; the origin climb column stays clear. |

## Marker scale

Each marker's black code is `0.2 m` square, matching `marker_size_m` used by
`aruco_pose_publisher` and `lib/aruco_detector.py` for pose estimation.
Generated textures pad that code with a `64 px` white quiet zone on every
side, so the rendered surface is `0.25 m` square. The extra 0.05 m is quiet
zone, not code: do not pass 0.25 m as `marker_size_m`.

## Limitations

**Boot path (default vs repo worlds).** PX4's rcS (`px4-rc.gzsim`) sources
`build/px4_sitl_default/rootfs/gz_env.sh`, which unconditionally resets
`PX4_GZ_WORLDS` to PX4's own worlds directory, so PX4 can only start Gazebo on
worlds it ships (`default`). For repo-only worlds, `_start_gz_px4.sh`
pre-starts a **paused** gz server on the repo SDF; PX4 then detects the running
world and adopts it via its first-class "gazebo already running" branch (which
never sources `gz_env.sh`, so no clobber). A watcher unpauses physics once PX4
has spawned the model, keeping sim time from free-running before lockstep (an
unpaused pre-start corrupts EKF2 timing, see the `_start_gz_px4.sh` header).
The `default` world keeps the original PX4-starts-Gazebo path byte-identical.
All three repo worlds now launch via `just sim --world <name>`.

The stock `x500` model in this template has no bridged camera topic, so
these worlds are GUI and manual flight practice only, not an automated
perception capability. `--vision aruco` in `sim_full.launch.py` bridges a
camera topic only if the selected model publishes one; the current x500
does not. Scenarios `05_aruco_hover` and `06_search_relocalize` remain
synthetic (fabricated detections) by design and do not depend on these
worlds. A future camera-equipped vehicle model could turn these environments
into true perception scenarios without changing their geometry.
