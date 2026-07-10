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

**Live boot is currently blocked for repo-only worlds.** PX4's rcS
(`px4-rc.gzsim`) sources `build/px4_sitl_default/rootfs/gz_env.sh`, which
unconditionally resets `PX4_GZ_WORLDS` to PX4's own worlds directory, so
Gazebo is asked to load `<PX4_DIR>/Tools/simulation/gz/worlds/<world>.sdf`
and repo-only worlds fail with "Unable to find or download file". `default`
still boots because PX4 ships its own `default.sdf`. Fixing this requires
either modifying `PX4_DIR` (forbidden invariant) or reworking the PX4/Gazebo
boot handoff in `sim/launch/_start_gz_px4.sh` (a separate plan; the handoff
is timing-sensitive, see the header of that script). Until then these worlds
validate with `gz sdf -k` but do not launch via `just sim --world ...`.

The stock `x500` model in this template has no bridged camera topic, so
these worlds are GUI and manual flight practice only, not an automated
perception capability. `--vision aruco` in `sim_full.launch.py` bridges a
camera topic only if the selected model publishes one; the current x500
does not. Scenarios `05_aruco_hover` and `06_search_relocalize` remain
synthetic (fabricated detections) by design and do not depend on these
worlds. A future camera-equipped vehicle model could turn these environments
into true perception scenarios without changing their geometry.
