# Plan 071: Scenario evidence hardening — shared fake camera, PX4 cross-checks, estimator-divergence tripwire

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in "STOP conditions" occurs, stop and report — do not
> improvise. When done, update this plan's row in `plans/README.md` unless a
> reviewer told you they maintain the index.
>
> **Drift check (run first)**:
> `git diff --stat 6ce9aec..HEAD -- tests/scenarios/ tests/unit/`
> On any mismatch with the "Current state" excerpts below, STOP.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: MED (tightens live assertions; a systematic frame offset could
  make a healthy run fail — see STOP conditions)
- **Depends on**: none. Requires a sim-capable machine for the final gate.
- **Category**: test-quality / correctness
- **Planned at**: commit `6ce9aec`, 2026-07-16

## Why this matters

Three scenarios (05, 06, 08) each carry a byte-similar ~60-line synthetic
nadir-camera renderer. The triplication has already drifted stylistically and
will drift behaviorally the first time someone fixes a projection bug in one
copy. Worse, most scenarios trust `/drone/odom` alone — which is produced by
our own `position_node` from PX4 data. A bug in our ENU conversion or
anchoring would corrupt both the flight AND the evidence that judges it.
Scenario 03 already fixed this class of problem ("a bug that advances the
index without the airframe flying the path is caught") by subscribing to
PX4's own `/fmu/out/vehicle_local_position_v1` and asserting independently.
This plan extends that pattern to 01, 05, and 06, dedupes the fake camera,
and adds a cheap tripwire that converts silent estimator divergence (the
plans/065 failure mode: z runs away after arming) into an immediate, named
scenario FAIL instead of a confusing timeout.

## Current state

- `tests/scenarios/_common.py` — shared helpers: `PX4_QOS` (lines 20–25, a
  deliberate copy of nodes/qos for path reasons), `spin_until`,
  `write_report`, `Scenario` base, `run_main`. No cv2/numpy imports today.
- Triplicated fake-camera render (identical math, cosmetic diffs):
  - `tests/scenarios/05_aruco_hover.py` `_timer_cb` lines 72–164
  - `tests/scenarios/06_search_relocalize.py` `_timer_cb` lines 83–150
  - `tests/scenarios/08_precision_land.py` `_publish_marker_frame` lines 152–214

  Shared constants in all three: 640x640 white canvas, `fx = fy = 500.0`,
  `cx = cy = 320.0`, `DICT_4X4_50`, physical marker size `0.2` m,
  `size_px = max(10, min(200, int(fx * 0.2 / z_c)))`, nadir body-to-camera
  mapping `x_c = -dy_body; y_c = -dx_body; z_c = -dz_body`, CameraInfo
  `k = [500, 0, 320, 0, 500, 320, 0, 0, 1]`. All render marker id 0 at ENU
  (8.0, 0.0).
- The PX4 cross-check precedent, `tests/scenarios/03_waypoint.py:39–52`:

  ```python
  self.create_subscription(
      VehicleLocalPosition, "/fmu/out/vehicle_local_position_v1", self._pos_cb, PX4_QOS
  )

  def _pos_cb(self, msg: VehicleLocalPosition) -> None:
      pos = ned_to_enu(msg.x, msg.y, msg.z)
  ```

  (`ned_to_enu` from `ros_px4_template_core.lib.frames`; scenarios may import
  from `lib` — 03, 05, 06, 08 already do.)
- `tests/scenarios/01_arm_takeoff.py` — procedural style; subscribes only
  `/drone/odom`, `/drone/controller_status`, `/drone/mission_status`. Hold
  check at lines 183–198; final report at 222–240.
- `tests/scenarios/05_aruco_hover.py` — passes if `marker_hover` entered and
  `/drone/target_pose` within 0.5 m of (8, 0) (lines 210–222). No independent
  altitude evidence: a target pose could be "correct" while the airframe sits
  on the ground.
- `tests/scenarios/06_search_relocalize.py` — passes on override_count > 0
  AND phase `done` via `return_to_origin` (lines 197–204). No independent
  evidence the airframe physically returned.
- In SITL, PX4's local origin and `position_node`'s ENU anchor are both the
  boot/takeoff location, so PX4-derived ENU and `/drone/odom` agree to within
  estimator noise — EXCEPT after a relocalization override (scenario 06),
  which legitimately shifts the anchored frame; the 06 check below is
  therefore deliberately loose.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Quality gate | `just check` | exit 0 |
| One live scenario | `just sim --vision aruco` then `just scenario 05_aruco_hover` | PASS |
| Full live gate | `just test e2e` | 8/8 PASS, exit 0 |
| Teardown between runs | `just stop` | clean |

All live commands run inside distrobox: `distrobox enter ubuntu -- bash -lc
'cd ~/Projects/ros-px4-template && just <recipe>'`.

## Scope

**In scope**:
- New file `tests/scenarios/_fake_camera.py`
- `tests/scenarios/_common.py` (one small pure helper, no new heavy imports)
- `tests/scenarios/01_arm_takeoff.py`, `05_aruco_hover.py`,
  `06_search_relocalize.py`, `08_precision_land.py`
- New unit test file `tests/unit/test_fake_camera.py`

**Out of scope** (do NOT touch):
- `09_aruco_hover_real.py` — it uses the REAL gz camera; no fake-camera code.
- `02_hover_hold.py`, `03_waypoint.py`, `07_yaw_control.py` — 03 already has
  the cross-check; 02/07 gain little (don't churn them).
- `src/` — this plan changes evidence collection, never flight behavior.
- Pass/fail thresholds of existing checks (only ADD checks; never loosen).

## Git workflow

- Branch: `advisor/071-scenario-evidence-hardening`
- Commit style: `test(scenarios): shared fake camera + independent PX4 cross-checks`
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Extract the fake camera into `tests/scenarios/_fake_camera.py`

A new module (NOT `_common.py`, so scenarios 01/02/03/07 don't pay the
cv2/numpy import) with pure render + message builders:

```python
"""Synthetic nadir camera shared by scenarios 05/06/08.

Renders a DICT_4X4_50 marker into a 640x640 white frame as seen from the
drone's live anchored-ENU pose, using the same intrinsics the scenarios have
always published (fx=fy=500, cx=cy=320). Pure functions; the scenario node
owns the publishers and timer.
"""

WIDTH = HEIGHT = 640
FX = FY = 500.0
CX = CY = 320.0
MARKER_SIZE_M = 0.2
K = [FX, 0.0, CX, 0.0, FY, CY, 0.0, 0.0, 1.0]


def render_marker_view(
    x: float, y: float, z: float, yaw: float,
    marker_x: float, marker_y: float, marker_id: int = 0,
) -> np.ndarray: ...


def build_camera_msgs(img: np.ndarray, stamp) -> tuple[Image, CameraInfo]: ...
```

`render_marker_view` is the verbatim math currently in 05's `_timer_cb`
(lines 89–142): ENU offset → `enu_offset_to_body_flu` → nadir camera frame →
perspective projection → clipped `generateImageMarker` blit. Copy it from 05,
do not re-derive it. `build_camera_msgs` is the Image/CameraInfo construction
from 05 lines 144–164.

Rewire 05, 06, and 08: each `_timer_cb` / `_publish_marker_frame` body
becomes read pose → `img = render_marker_view(x, y, z, yaw, MARKER_X,
MARKER_Y)` → `image, info = build_camera_msgs(img,
self.get_clock().now().to_msg())` → publish both. 08 keeps its
`publish_marker` gating around the call (the marker-loss stages are the point
of that scenario). Keep each scenario's own `_MARKER_X/_MARKER_Y` constants.

**Verify**: `just check` → exit 0 (build + unit). Behavior check comes in
step 5's live gate.

### Step 2: Unit tests for the extracted renderer

New `tests/unit/test_fake_camera.py` (pure, no rclpy spin — instantiate
messages directly):

- `test_marker_visible_directly_below`: drone at (8, 0, 3), yaw 0, marker at
  (8, 0) → the rendered frame contains non-white pixels near (320, 320), and
  `cv2.aruco.detectMarkers` with DICT_4X4_50 finds id 0.
- `test_marker_off_frame_renders_blank`: drone at (100, 100, 3) → frame is
  all white.
- `test_camera_info_intrinsics_pinned`: `build_camera_msgs` sets
  `info.k == K` and `image.encoding == "bgr8"`, `step == WIDTH * 3` (pins the
  contract `aruco_pose_publisher` consumes).

Note: `tests/scenarios/` is not on the unit-test path by default — add
`sys.path.insert` the same way existing unit tests import from `tools/`
(check `tests/unit/test_scenario_roster.py` for the conftest/path idiom and
copy it).

**Verify**: `uv run pytest tests/unit/test_fake_camera.py -q` → all pass.

### Step 3: Estimator-divergence tripwire

In `_common.py`, add a tiny pure helper (no new imports beyond `math` if
needed):

```python
PHYS_BOUND_M = 500.0


def pose_out_of_bounds(x: float, y: float, z: float, bound_m: float = PHYS_BOUND_M) -> bool:
    """True when a pose is physically impossible for this template's worlds —
    the plans/065 estimator-runaway signature. Scenarios use it to fail fast
    with reason 'estimator_diverged' instead of timing out confusingly."""
    return not (abs(x) < bound_m and abs(y) < bound_m and abs(z) < bound_m)
```

Wire it into the odom callbacks of 01, 05, 06, 08: set a
`self.estimator_diverged = True` flag when it trips, and make the scenario's
done/fail path report `reason: "estimator_diverged"` with the offending pose
in the detail dict (procedural scenarios: check the flag at the top of the
`done()` predicate and in the post-`spin_until` assertions; 08 uses the
`Scenario` base? — check its style and follow it).

**Verify**: unit test in `test_fake_camera.py` or a new
`test_scenario_helpers.py`: `pose_out_of_bounds(0, 0, 3)` is False;
`pose_out_of_bounds(0, 0, 9999)` is True.

### Step 4: Independent PX4 cross-checks (pattern of 03)

Each subscribes `/fmu/out/vehicle_local_position_v1` with `PX4_QOS` and
converts via `ned_to_enu` exactly as `03_waypoint.py:47–52` does. New checks
ADD fail conditions; every new failure gets its own `reason` string.

- **01_arm_takeoff**: track latest PX4 ENU z. At the final verdict (after the
  hold), require `abs(px4_z_enu - node.z_enu) <= 0.8` → else FAIL
  `"px4_odom_divergence"` with both values in detail. Also include
  `px4_z_enu` in the PASS detail (flight evidence in the report).
- **05_aruco_hover**: at the moment the pass condition is evaluated (entered
  `marker_hover` with a target pose), require latest `px4_z_enu > 1.5` →
  else FAIL `"px4_altitude_implausible"` (catches a "correct" target pose
  computed while the airframe never actually flew).
- **06_search_relocalize**: record the FIRST PX4 ENU (x, y) seen as
  `start_xy`. At `done`, require the latest PX4 horizontal distance from
  `start_xy` to be `< 2.0` m → else FAIL `"px4_drift_from_start"`. The band
  is deliberately loose: the relocalization override shifts the anchored
  `/drone/odom` frame, but PX4's own local frame is untouched, so "physically
  returned near launch" is the strongest claim that stays valid. Do NOT
  tighten below 2.0 m.
- **08_precision_land**: no new PX4 check (its `min_z_seen` / freeze checks
  already come from odom AND the scenario's value is the loss-handling logic;
  adding a descent cross-check is optional and only if trivially clean).

**Verify**: `just check` → exit 0. Then one live spot check:
`just sim --vision aruco`, `just scenario 05_aruco_hover` → PASS with
`px4` evidence visible in `logs/scenario_05_aruco_hover.json`; `just stop`.

### Step 5: Full live gate (operator-visible)

Run `just test e2e` (blocks; ~25 min). Expected: 8/8 PASS. Inspect
`logs/scenario_01_arm_takeoff.json` and `logs/scenario_06_search_relocalize.json`
for the new evidence fields. Run it TWICE if time allows — the new checks
must not introduce flakiness.

**Verify**: aggregate PASS, exit 0, and `rg estimator_diverged logs/` → no
matches on a healthy run.

## Test plan

- Unit: renderer visibility/blank/intrinsics tests (step 2), bounds helper
  test (step 3).
- Live: one scenario spot check (step 4), full e2e twice (step 5).
- Negative check is implicit: the new reasons (`px4_odom_divergence`,
  `px4_altitude_implausible`, `px4_drift_from_start`, `estimator_diverged`)
  only ever appear on genuinely bad runs; do not build a fault injector for
  them in this plan.

## Done criteria

- [ ] `rg -c "generateImageMarker" tests/scenarios/` → matches only in `_fake_camera.py` (05/06/08 render via the shared module)
- [ ] `uv run pytest tests/unit/test_fake_camera.py -q` → all pass
- [ ] 01, 05, 06 subscribe `/fmu/out/vehicle_local_position_v1`; 01's PASS report contains PX4 z evidence
- [ ] `pose_out_of_bounds` wired into 01/05/06/08 odom callbacks
- [ ] `just check` → exit 0
- [ ] `just test e2e` → 8/8 PASS (run on a sim-capable machine)
- [ ] `plans/README.md` status row updated

## STOP conditions

- The live e2e fails with one of the NEW reasons on an otherwise-healthy run
  (e.g. `px4_odom_divergence` with a systematic ~constant offset): the frame
  assumption in "Current state" is wrong for that scenario. STOP, report the
  measured offset, and do not widen the tolerance yourself.
- Extracting the renderer changes any scenario's detection behavior (05/06/08
  stop passing where they passed before): diff your extracted math against
  the original 05 block line by line; if identical and still failing, STOP.
- `09_aruco_hover_real` or anything under `src/` would need modification.

## Maintenance notes

- `_fake_camera.py`'s intrinsics are a contract with
  `aruco_pose_publisher`'s pose math; if the real camera model
  (`x500_mono_cam_down`) changes FOV or resolution, the fake stays as-is —
  it emulates an idealized camera, not the gz sensor.
- New scenarios needing synthetic vision must import `_fake_camera` rather
  than re-inlining the render block; reviewers should reject new copies.
- The 2.0 m band in 06 encodes "relocalization shifts the anchored frame";
  see plans/README round-6 notes before touching it.
