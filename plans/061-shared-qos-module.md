# Plan 061: One `lib/qos.py` for the five copy-pasted QoS profiles (+ name the detection-freshness constant)

> **Executor instructions**: Follow this plan step by step, verifying each
> step. On any STOP condition, stop and report. When done, update
> `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 01f94c7..HEAD -- src/core/ros_px4_template_core/nodes/ src/core/ros_px4_template_core/lib/`
> On any mismatch with the excerpts below, STOP.

## Status

- **Priority**: P3
- **Effort**: S
- **Risk**: LOW (pure constant relocation; QoS values byte-identical before/after)
- **Depends on**: none (trivial merge with 057 if both touch the nodes; land in either order)
- **Category**: tech-debt
- **Planned at**: commit `01f94c7`, 2026-07-10

## Why this matters

The same two QoS contracts are hand-duplicated across all five nodes. ROS 2
QoS incompatibility fails **silently** — a mismatched publisher/subscriber
pair simply never connects, no error — so the day someone edits one copy
(depth, durability) the symptom is "topic just doesn't deliver", one of the
most expensive classes of bug to diagnose. The profiles are the interop
contract on `/drone/*` and the `/fmu/*` boundary; contracts get one home.
Bundled (same theme, 2 lines): `mission_manager` gates detection freshness on
a bare `1.0` duplicated at two sites next to a properly named sibling
constant.

## Current state

Byte-identical module constants (verified):

- `nodes/offboard_controller.py:57-67` — `_PX4_QOS` (BEST_EFFORT +
  TRANSIENT_LOCAL + KEEP_LAST + depth 10) and `_RELIABLE_QOS` (RELIABLE +
  KEEP_LAST + depth 10)
- `nodes/position_node.py:47-52` — `_PX4_QOS`; plus node-local `_ODOM_QOS`
  (RELIABLE + VOLATILE + depth 10, `:53-58`) and `_LATCHED_QOS` (RELIABLE +
  TRANSIENT_LOCAL + depth 1, `:59-64`)
- `nodes/mission_manager.py:56-64` — `_RELIABLE_QOS` and `_PX4_QOS`
- `nodes/marker_localizer.py:34` and `nodes/aruco_pose_publisher.py:29-33` —
  `_RELIABLE_QOS`
- `tests/scenarios/_common.py:19-24` — `PX4_QOS` (same values; scenarios
  deliberately have no `src/` import path — see its comment `:94-95` "this
  module has no tools/ on its path" — LEAVE IT, but add a pointer comment)

The freshness literal: `nodes/mission_manager.py:232` and `:236` both
hardcode `1.0` for the detection-validity window; the sibling
`_STABLE_FRESH_S = 0.3` is named at `:65`.

Repo conventions: `lib/` modules are rclpy-free "where possible"
(AGENTS.md) — QoS profiles inherently need `rclpy.qos`, which is acceptable
for a nodes-facing lib module, but the module must import ONLY `rclpy.qos`
(no Node, no messages), keeping it importable without a running graph.

## Commands you will need

| Purpose | Command | Expected |
|---------|---------|----------|
| Quality gate | `just check` | exit 0 |
| Grep gate | `grep -rn "QoSProfile(" src/core/ros_px4_template_core/nodes/` | only sites listed as intentional below |
| Live regression | `just sim` + `just log topics` | READY; 12 OK |

## Scope

**In scope**:
- `src/core/ros_px4_template_core/lib/qos.py` (new)
- The five node files (imports + constant removal)
- `nodes/mission_manager.py` (`_DETECTION_FRESH_S` constant)
- `tests/scenarios/_common.py` (comment only)

**Out of scope**:
- Changing ANY QoS value, depth, or policy — this is a move, not a review
- `tests/scenarios/_common.py`'s own `PX4_QOS` definition (scenarios are
  intentionally self-contained)
- The one-off inline profile in `offboard_controller.py:165-170`
  (`/drone/local_origin` subscriber, depth-1 latched) — name it
  `LATCHED_QOS` in the new module ONLY IF it is byte-identical to
  position_node's `_LATCHED_QOS` (it is: RELIABLE + TRANSIENT_LOCAL +
  KEEP_LAST + depth 1); then both use it

## Git workflow

- Branch: `advisor/061-shared-qos`
- Commit style: `refactor(core): single-source QoS profiles in lib/qos.py`

## Steps

### Step 1: Create `lib/qos.py`

```python
"""Single home for the project's QoS contracts.

ROS 2 QoS incompatibility fails silently (publisher and subscriber simply
never connect), so these profiles are defined once. PX4_QOS matches PX4
uXRCE-DDS publishers (rmw_qos_profile_sensor_data + TRANSIENT_LOCAL).
tests/scenarios/_common.py keeps an intentionally self-contained copy.
"""

from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy

PX4_QOS = QoSProfile(
    reliability=ReliabilityPolicy.BEST_EFFORT,
    durability=DurabilityPolicy.TRANSIENT_LOCAL,
    history=HistoryPolicy.KEEP_LAST,
    depth=10,
)
RELIABLE_QOS = QoSProfile(
    reliability=ReliabilityPolicy.RELIABLE,
    history=HistoryPolicy.KEEP_LAST,
    depth=10,
)
ODOM_QOS = QoSProfile(  # /drone/odom: reliable, volatile (fresh data only)
    reliability=ReliabilityPolicy.RELIABLE,
    durability=DurabilityPolicy.VOLATILE,
    history=HistoryPolicy.KEEP_LAST,
    depth=10,
)
LATCHED_QOS = QoSProfile(  # depth-1 transient-local: late joiners get the last value
    reliability=ReliabilityPolicy.RELIABLE,
    durability=DurabilityPolicy.TRANSIENT_LOCAL,
    history=HistoryPolicy.KEEP_LAST,
    depth=1,
)
```

### Step 2: Rewire the five nodes

Replace each module-level `_PX4_QOS`/`_RELIABLE_QOS`/`_ODOM_QOS`/`_LATCHED_QOS`
definition with `from ros_px4_template_core.lib.qos import ...` and update the
usage names (keep the leading-underscore locals OR use the imported names
directly — pick direct import, smaller diff). In `offboard_controller.py`
replace the inline `/drone/local_origin` QoSProfile (`:165-170`) with
`LATCHED_QOS`.

**Verify after each file**: `just check` → exit 0 (symlink-install means the
build step catches import errors).

### Step 3: Name the freshness constant

In `mission_manager.py`, next to `_STABLE_FRESH_S`:
`_DETECTION_FRESH_S = 1.0  # a detection is usable if newer than this` and use
it at both comparison sites (`:232`, `:236`). If plan 057 landed first, the
sites live in `lib/mission_inputs.py` — apply there (its `stable_fresh_s`
kwarg pattern shows the shape).

### Step 4: Pointer comment in `_common.py`

Above `PX4_QOS` in `tests/scenarios/_common.py`, extend the existing comment:
`# Kept as a deliberate copy of lib/qos.PX4_QOS (scenario scripts run without src/ on the path).`

### Step 5: Live regression

`just sim` → READY; `just log topics` → all 12 `[OK]` (this is the QoS
compatibility proof: every pub/sub pair still connects);
`just scenario 01_arm_takeoff` → PASS; `just stop`.

## Done criteria

- [ ] `grep -rn "QoSProfile(" src/core/ros_px4_template_core/nodes/` → zero matches (all imported)
- [ ] `lib/qos.py` imports nothing beyond `rclpy.qos`
- [ ] `grep -n "1.0" src/core/ros_px4_template_core/nodes/mission_manager.py` shows no bare detection-window literal (both sites use `_DETECTION_FRESH_S`)
- [ ] `just check` exit 0; `just log topics` 12 OK; scenario 01 PASS (operator)
- [ ] `plans/README.md` row updated

## STOP conditions

- Any of the five per-node profiles is NOT byte-identical to the canonical
  values above (mis-verified duplication) — report the diff; a deliberate
  divergence must stay divergent and documented, not silently unified.
- `lib/qos.py` triggers the `lib/` rclpy-free lint/check (if `just check`
  enforces it mechanically) — report; the fallback home is
  `nodes/_qos.py`, but confirm with the owner before inventing a new
  convention.

## Maintenance notes

- New nodes must import from `lib/qos.py`; a reviewer seeing a fresh inline
  `QoSProfile(` in `nodes/` should push back.
- If the scenario harness ever gains a src/ path, fold `_common.PX4_QOS` in
  and delete the copy.
