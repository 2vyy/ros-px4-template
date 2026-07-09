# Plan 038: Stop rebuilding the ArUco detector on every camera frame

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report - do not improvise. When done, update the status row for this plan
> in `plans/README.md` - unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat ead4cc6..HEAD -- src/core/ros_px4_template_core/lib/aruco_detector.py tests/unit/test_aruco_detector.py`
> If either changed, compare the "Current state" excerpt before proceeding;
> on a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: perf
- **Planned at**: commit `ead4cc6`, 2026-07-06

## Why this matters

`detect_markers` runs once per `/camera/image_raw` frame
(`nodes/aruco_pose_publisher.py:88`, called from `_image_cb`), and every call
constructs a fresh `getPredefinedDictionary` + `DetectorParameters` +
`ArucoDetector` triple before doing any detection. At camera rate that is
3 allocations per frame of objects that never change for a given
`dictionary_id`. On a competition machine sharing CPU with Gazebo, PX4 SITL,
and the ROS graph, this is free latency to reclaim in the vision hot path.

## Current state

- `src/core/ros_px4_template_core/lib/aruco_detector.py` - pure OpenCV, no ROS.
  The per-call construction (lines 39-42):

```python
    aruco_dict = cv2.aruco.getPredefinedDictionary(dictionary_id)
    params = cv2.aruco.DetectorParameters()
    detector = cv2.aruco.ArucoDetector(aruco_dict, params)
    corners, ids, _ = detector.detectMarkers(image)
```

- `detect_markers` signature: `(image, camera_matrix, dist_coeffs, marker_size_m=0.2, dictionary_id=cv2.aruco.DICT_4X4_50)`.
- Caller: `nodes/aruco_pose_publisher.py:88` (never passes `dictionary_id`,
  so the default is the only id exercised at runtime today).
- The node spins on a plain single-threaded `rclpy.spin`, so `_image_cb` calls
  are serialized - a shared detector object is never used concurrently within
  one process.
- Tests: `tests/unit/test_aruco_detector.py` exists (synthetic-image tests).

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Unit tests | `uv run pytest tests/unit/test_aruco_detector.py -q` | all pass |
| Lint | `uv run ruff check src/core/ros_px4_template_core/lib/aruco_detector.py` | exit 0 |
| Full gate | `just check` | exit 0 |

## Scope

**In scope**:
- `src/core/ros_px4_template_core/lib/aruco_detector.py`
- `tests/unit/test_aruco_detector.py`

**Out of scope**:
- `nodes/aruco_pose_publisher.py` - its call site does not change.
- Detection parameters/tuning - `DetectorParameters()` defaults stay exactly
  as they are.
- Any threading machinery; the single-threaded assumption above is documented,
  not "fixed".

## Git workflow

- Branch: `advisor/038-cache-aruco-detector`
- Commit style: `perf(vision): cache the ArucoDetector per dictionary id`
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Add a cached detector factory

In `lib/aruco_detector.py`, add near the top (after imports):

```python
from functools import lru_cache


@lru_cache(maxsize=8)
def _get_detector(dictionary_id: int) -> cv2.aruco.ArucoDetector:
    """One detector per dictionary; construction is pure and parameters are defaults."""
    aruco_dict = cv2.aruco.getPredefinedDictionary(dictionary_id)
    params = cv2.aruco.DetectorParameters()
    return cv2.aruco.ArucoDetector(aruco_dict, params)
```

Then replace lines 39-42 of `detect_markers` with:

```python
    detector = _get_detector(dictionary_id)
    corners, ids, _ = detector.detectMarkers(image)
```

Keep the module docstring, the camera-matrix guard clause, and everything
below `detectMarkers` untouched. Match the file's comment style (it explains
constraints, e.g. the SOLVEPNP_IPPE_SQUARE note - do not add narration
comments).

**Verify**: `uv run pytest tests/unit/test_aruco_detector.py -q` -> existing tests pass

### Step 2: Pin the caching behavior with tests

Add to `tests/unit/test_aruco_detector.py`:

1. `test_detector_cached_per_dictionary`: `_get_detector(cv2.aruco.DICT_4X4_50)`
   twice returns the SAME object (`is`); `_get_detector(cv2.aruco.DICT_5X5_50)`
   returns a DIFFERENT object.
2. `test_detection_unchanged_after_cache`: reuse (or copy) an existing
   synthetic-image test in the file and assert results are identical across two
   consecutive `detect_markers` calls on the same image (same ids, same pixel
   centers) - pins that a reused detector is stateless across calls.

**Verify**: `uv run pytest tests/unit/test_aruco_detector.py -q` -> all pass (2 new)

### Step 3: Full gate

**Verify**: `just check` -> exit 0

## Test plan

Step 2's two tests: cache identity per dictionary id, and detection-result
stability across reuse. The existing synthetic-image tests keep covering the
detection math itself.

## Done criteria

- [ ] `uv run pytest tests/unit/test_aruco_detector.py -q` passes with 2 new tests
- [ ] `rg -n "lru_cache" src/core/ros_px4_template_core/lib/aruco_detector.py` -> match
- [ ] `rg -n "getPredefinedDictionary" src/core/ros_px4_template_core/lib/aruco_detector.py` shows it only inside `_get_detector`
- [ ] `just check` exits 0
- [ ] `git status` shows only in-scope files modified
- [ ] `plans/README.md` status row updated

## STOP conditions

- The excerpted lines 39-42 are not as shown (drift).
- The reuse test (Step 2.2) fails - that would mean `ArucoDetector` carries
  state across `detectMarkers` calls in this OpenCV build; report it, do not
  work around it.
- Any test in the file needs different `DetectorParameters` per call - the
  cache key would need to grow; report instead of extending the design.

## Maintenance notes

- If a fork ever needs non-default `DetectorParameters`, the cache key must
  include them (or the cache must go); the `maxsize=8` and the docstring say
  "parameters are defaults" on purpose.
- Reviewer: confirm no behavior-visible change - the diff should be
  construction-hoisting only.
