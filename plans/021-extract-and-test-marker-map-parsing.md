# Plan 021: Marker-map parsing is pure, validated, and unit-tested

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving on. If
> anything in "STOP conditions" occurs, stop and report. When done, update this
> plan's row in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 0f93f0e..HEAD -- src/core/ros_px4_template_core/nodes/marker_localizer.py`
> If it changed, compare the "Current state" excerpt to the live code before
> proceeding; on a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: LOW
- **Depends on**: none
- **Category**: tests
- **Planned at**: commit `0f93f0e`, 2026-06-22

## Why this matters

Vision relocalization is a critical capability, but the parsing of the marker map
lives inline inside the `marker_localizer` ROS node, so it has **zero unit
coverage** (only the live scenarios 05/06 touch it, a ~2-minute feedback loop).
The current inline parse is also fragile: a malformed map entry (missing `x`/`y`/
`z`, or a non-numeric value) raises `KeyError`/`ValueError` during node
construction and **crashes the node** instead of skipping the bad entry. This
plan extracts the parse into a pure, `rclpy`-free `lib/` function with
validation, unit-tests it directly (no ROS graph needed), and has the node call
it. This both adds the missing coverage and hardens the crash path — a single
small, low-risk change.

## Current state

`src/core/ros_px4_template_core/nodes/marker_localizer.py:56-63`:
```python
        p = Path(str(self.get_parameter("marker_map_file").value))
        if not p.is_absolute():
            p = _project_root() / p
        doc = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        self._map: dict[int, tuple[float, float, float]] = {
            int(k): (float(v["x"]), float(v["y"]), float(v["z"]))
            for k, v in (doc.get("markers") or {}).items()
        }
```
A `markers` entry missing a key, or with a non-numeric value, throws and the node
dies in `__init__`. (The default `marker_map_file` is `config/markers.yaml`,
which does not currently exist in the repo — missions that relocalize supply the
file via a param overlay.)

The node already imports from `lib`:
```python
from ros_px4_template_core.lib.frames import (
    drone_pose_from_marker, enu_quaternion_from_yaw, enu_yaw_from_quaternion,
)
from ros_px4_template_core.lib.structured_logger import StructuredLogger
```
`lib/` is required to stay `rclpy`-free (per `AGENTS.md`), and unit tests import
`ros_px4_template_core.lib...` directly because `tests/conftest.py:7` puts
`src/core` on `sys.path` (no colcon build needed).

`drone_pose_from_marker` and `camera_to_body` (the frame math the node uses) are
**already** unit-tested in `tests/unit/test_frames.py`, so this plan targets only
the untested glue: the map parse.

Pattern to match for the new lib module: small, pure, typed, google-style
docstring — see `lib/setpoint_hold.py` or `lib/waypoint_mission.py`. Pattern for
the test file: `tests/unit/test_aruco_detector.py` (imports the lib function,
asserts on outputs, no ROS).

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Run new tests | `uv run pytest tests/unit/test_marker_map.py -q` | all pass |
| Full unit suite | `uv run pytest tests/unit/ -q` | all pass |
| Lint | `uv run ruff check src/core/ros_px4_template_core/lib/marker_map.py src/core/ros_px4_template_core/nodes/marker_localizer.py tests/unit/test_marker_map.py` | exit 0 |
| Typecheck | `uv run ty check src/core/ros_px4_template_core/lib tests/unit tools/` | exit 0 |

## Scope

**In scope**:
- `src/core/ros_px4_template_core/lib/marker_map.py` (create) — pure
  `parse_marker_map(doc)` with validation.
- `tests/unit/test_marker_map.py` (create) — unit tests.
- `src/core/ros_px4_template_core/nodes/marker_localizer.py` (modify) — call the
  new function; keep behavior identical for well-formed maps.

**Out of scope** (do NOT touch):
- `lib/frames.py` and `test_frames.py` — the frame math is already tested.
- Other nodes, the engine, the loader.
- The default `marker_map_file` path / adding a `config/markers.yaml` — not part
  of this plan.

## Git workflow

- Branch: `advisor/021-marker-map-parse-tests`
- Conventional commits (e.g.
  `refactor(marker_localizer): extract + test marker-map parsing, skip bad entries`).
- Do NOT push or open a PR unless instructed.

## Steps

### Step 1: Create the pure parser in `lib/marker_map.py`

Write a `rclpy`-free function that turns the loaded YAML doc into the
`{id: (x,y,z)}` map, **skipping** malformed entries (and optionally reporting
them) instead of raising. Target shape:
```python
"""Pure parsing of a marker-map document into {marker_id: (x, y, z)} (ENU)."""
from __future__ import annotations


def parse_marker_map(doc: dict | None) -> tuple[dict[int, tuple[float, float, float]], list[str]]:
    """Return (map, warnings).

    ``map`` is {int marker id: (x, y, z) float ENU}. ``warnings`` lists one
    human-readable string per skipped malformed entry, so a caller can log them
    without the parse ever raising on bad input.
    """
    out: dict[int, tuple[float, float, float]] = {}
    warnings: list[str] = []
    markers = (doc or {}).get("markers") or {}
    if not isinstance(markers, dict):
        return ({}, [f"'markers' is not a mapping: {type(markers).__name__}"])
    for k, v in markers.items():
        try:
            mid = int(k)
            x, y, z = float(v["x"]), float(v["y"]), float(v["z"])
        except (KeyError, TypeError, ValueError) as e:
            warnings.append(f"marker {k!r}: {type(e).__name__}: {e}")
            continue
        out[mid] = (x, y, z)
    return (out, warnings)
```

**Verify**: `uv run ruff check src/core/ros_px4_template_core/lib/marker_map.py`
→ exit 0.

### Step 2: Use it from the node

In `marker_localizer.py`, replace the inline dict comprehension (lines 59-63)
with a call to `parse_marker_map`, and log any warnings via the node's
`StructuredLogger` instead of crashing. Target:
```python
        from ros_px4_template_core.lib.marker_map import parse_marker_map
        doc = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        self._map, warnings = parse_marker_map(doc)
        for w in warnings:
            self.slog.info("marker_map: skipped malformed entry", detail=w)
```
(Put the import at the top of the file with the other `lib` imports rather than
inline if that matches the file's style; the inline form above is only to show
intent.) Behavior for a **well-formed** map is byte-for-byte identical to today.

**Verify**: `uv run ruff check src/core/ros_px4_template_core/nodes/marker_localizer.py`
→ exit 0; visually confirm the `self._map` type annotation and the subsequent
`self.slog.info("marker_localizer ready", markers=sorted(self._map))` line still
work (the map shape is unchanged).

### Step 3: Unit-test the parser

Create `tests/unit/test_marker_map.py`, modeled on `test_aruco_detector.py`
(import the function, assert on outputs, no ROS). Cover:
- A well-formed two-marker doc → both ids present with correct float tuples,
  empty warnings.
- Integer-string keys (`"0"`, `"1"` as YAML map keys) coerce to `int`.
- An entry missing `z` → that id skipped, one warning, the others still present.
- A non-numeric value (`x: "abc"`) → that id skipped with a warning.
- `doc=None` and `doc={}` → empty map, no crash.
- `markers` present but not a mapping (e.g. a list) → empty map, one warning.

**Verify**: `uv run pytest tests/unit/test_marker_map.py -q` → all pass.

## Test plan

- New `tests/unit/test_marker_map.py` with the six cases above (≥6 tests),
  modeled structurally on `tests/unit/test_aruco_detector.py`.
- No live scenario is required for this plan (the well-formed path is unchanged),
  but if the operator runs `just scenario 06_search_relocalize` it must still
  PASS.
- Verification: `uv run pytest tests/unit/ -q` → all pass.

## Done criteria

ALL must hold:

- [ ] `src/core/ros_px4_template_core/lib/marker_map.py` exists, is `rclpy`-free, and `parse_marker_map` never raises on bad input
- [ ] `marker_localizer.py` calls `parse_marker_map` and logs warnings instead of crashing
- [ ] `uv run pytest tests/unit/test_marker_map.py -q` passes (≥6 cases)
- [ ] `uv run pytest tests/unit/ -q` exits 0 (no regressions)
- [ ] `uv run ruff check <the three files>` exits 0
- [ ] `uv run ty check src/core/ros_px4_template_core/lib tests/unit tools/` exits 0
- [ ] Only the in-scope files are modified
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report if:

- `marker_localizer.py:56-63` does not match "Current state" (the node drifted).
- Importing `ros_px4_template_core.lib.marker_map` in a unit test fails with a
  ROS/`rclpy` import error — the new module must stay pure; do not add ROS deps.
- The well-formed-map behavior would change (e.g. a different map type or key
  coercion) — keep it identical; only the malformed path should differ.

## Maintenance notes

- This is the pattern for the rest of the node-glue test gap: thin ROS nodes
  should delegate parsing/decisions to pure `lib/` functions that unit tests can
  reach. If `aruco_pose_publisher`'s target-selection logic ever grows beyond the
  already-tested `camera_to_body`, extract and test it the same way (deliberately
  deferred here — its current logic is thin glue over tested frame math).
- Reviewer: confirm the well-formed path is unchanged and the warnings are
  logged, not swallowed silently.
