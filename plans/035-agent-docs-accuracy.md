# Plan 035: Agent-facing docs stop naming dead identifiers (CLAUDE.md "If X fails" table + FRAMES.md "Mission pose")

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report - do not improvise. When done, update the status row for this plan
> in `plans/README.md` - unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat ead4cc6..HEAD -- CLAUDE.md AGENTS.md docs/FRAMES.md`
> Note: `CLAUDE.md` is a symlink to `AGENTS.md` - edit `AGENTS.md`. On any
> drift, compare excerpts before proceeding.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW (doc-only)
- **Depends on**: none
- **Category**: docs
- **Planned at**: commit `ead4cc6`, 2026-07-06

## Why this matters

The "If X fails" table in AGENTS.md is the first thing an autonomous agent
reads when a scenario fails, and today it sends the agent to identifiers that
do not exist: a `hover_marker` phase (actual: `marker_hover`), an
`enable_vision:=true` flag (actual: `--vision aruco`), a `/vision/marker_pose`
topic (actual: `/drone/marker_detection`), an `arm_delay_s` "default 3s"
(actual: 10.0 in sim), deleted `sim_pose_adapter`/`px4_pose_adapter` nodes
(actual: `position_node`), and a `just sim headless` invocation that errors
(headless is the default). FRAMES.md's "Mission pose" section likewise
describes a retired `/drone/pose_enu` topic and the deleted adapter nodes.
Wrong docs are worse than missing docs: they cost the agent a full
wrong-hypothesis loop on the two hardest debug paths (arming, vision).

## Current state

- `AGENTS.md` - the agent operating guide (CLAUDE.md symlinks to it).
- `docs/FRAMES.md` - frames doc; the stale "Mission pose" paragraph.

Stale lines in `AGENTS.md` (line numbers from `CLAUDE.md`, same file):

- Line 130 (sim-hangs row): "... try `just sim headless`"
- Line 132 (arm-fail row): "... `arm_delay_s` in `config/params/sim.yaml` (default 3s)"
- Line 133 (wait_arm_altitude row): "In sim check `sim_pose_adapter` / Gazebo
  pose; on hardware check `px4_pose_adapter` for `First pose published`
  (`xy_valid` and `z_valid`)."
- Line 134 (vision row): "Mission never enters `hover_marker` |
  `enable_vision:=true` needed; `/vision/marker_pose` valid;
  `marker.acquire_frames` consecutive frames must be hit"

Stale paragraph in `docs/FRAMES.md` (the "## Mission pose" section, around
line 46-48):

```
`mission_manager` uses `/drone/pose_enu` (`geometry_msgs/PoseStamped`, frame `map`, `RELIABLE` QoS). In sim, `sim_pose_adapter` publishes Gazebo ground truth; on hardware, `px4_pose_adapter` republishes PX4 NED as ENU. Mission logic blends pose z with `controller_status.altitude_enu_m` until pose is live. Do not feed mission logic raw `/fmu/out/vehicle_local_position`.
```

Ground truth to write against (verified in code at `ead4cc6`):

- Pose source of truth: `position_node` publishes `/drone/odom`
  (`nav_msgs/Odometry`); `mission_manager` subscribes to it
  (`nodes/mission_manager.py:93-94`). `docs/TOPICS.md` rows 19/33 agree.
- `arm_delay_s`: `config/params/sim.yaml:4` = 10.0; `hardware.yaml:6` = 5.0;
  node fallback `nodes/offboard_controller.py:69` = 15.0.
- Vision phase name: `marker_hover` (`tests/capabilities.toml`, scenario 05).
- Vision enablement: `just sim --vision aruco` (flag), `vision:=aruco`
  (launch arg) - see `tasks.py` sim options and `sim_full.launch.py`.
- Vision topics: `/drone/marker_detection` (detections),
  `/drone/pose_override` (relocalization fix) - `docs/TOPICS.md`.
- Marker stability: the `marker_stable` guard with param `n` (default 5) -
  `lib/mission/guards.py:51-57`; there is no `marker.acquire_frames` param.
- Altitude gate blend: `mission_manager._snapshot` uses
  `z_eff = max(self._pos_enu[2], self._ctrl_alt)` - the blend claim is still
  true; only the node/topic names around it are wrong.
- House style (AGENTS.md bottom): terse, table-heavy, no em dashes, no
  Unicode arrows.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Verify no dead identifiers remain | see Done criteria greps | no matches |
| Full gate (docs are not linted, but run it anyway) | `just check` | exit 0 |

## Scope

**In scope**:
- `AGENTS.md` (rows 130-134 of the "If X fails" table only)
- `docs/FRAMES.md` ("Mission pose" section only)

**Out of scope**:
- `docs/superpowers/plans/*.md` - historical archives; they mention the old
  architecture on purpose. Do not touch.
- `README.md`, `docs/TOPICS.md`, `docs/MISSIONS.md` - already accurate.
- Any other row of the "If X fails" table.

## Git workflow

- Branch: `advisor/035-agent-docs-accuracy`
- Commit style: `docs: fix dead identifiers in AGENTS.md failure table and FRAMES.md mission pose`
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Fix the four AGENTS.md rows

Apply these edits (keep each row's table shape):

1. Line 130: replace "try `just sim headless`" with "`just sim` is headless by
   default (GUI only via `--gui`)".
2. Line 132: replace "(default 3s)" with "(sim default 10s, hardware 5s)".
3. Line 133: replace the sentence "In sim check `sim_pose_adapter` / Gazebo
   pose; on hardware check `px4_pose_adapter` for `First pose published`
   (`xy_valid` and `z_valid`)." with: "Check `position_node` output:
   `rg src=position_node logs/latest.log` and confirm `/drone/odom` is
   publishing (`just log topics`)." Before writing, grep what `position_node`
   actually logs on first pose (`rg -n "slog|First pose" src/core/ros_px4_template_core/nodes/position_node.py`)
   and reference a string that exists; if none is distinctive, keep the
   generic wording above.
4. Line 134: replace the row content with: "Mission never enters
   `marker_hover` | boot with `just sim --vision aruco`; check
   `/drone/marker_detection` publishes valid detections
   (`rg src=aruco_pose_publisher logs/latest.log`); the `marker_stable` guard
   needs `n` consecutive fresh detections (default 5)".

**Verify**: `rg -n "hover_marker|enable_vision|/vision/marker_pose|sim_pose_adapter|px4_pose_adapter|sim headless|default 3s" AGENTS.md` -> no matches

### Step 2: Rewrite FRAMES.md "Mission pose"

Replace the stale paragraph with (adjust only if your Step 1 greps contradict
it):

```
`mission_manager` consumes `/drone/odom` (`nav_msgs/Odometry`, frame `map`,
`RELIABLE` QoS), published by `position_node` from PX4's
`/fmu/out/vehicle_local_position_v1` in the anchored ENU frame (see
[TOPICS.md](TOPICS.md)). Mission logic blends odom z with
`controller_status.altitude_enu_m` (`z_eff = max(pose_z, controller_alt)`)
so the takeoff gate works before the first odom fix. Do not feed mission
logic raw `/fmu/out/vehicle_local_position` - it is NED and unanchored.
```

**Verify**: `rg -n "pose_enu|sim_pose_adapter|px4_pose_adapter" docs/FRAMES.md` -> no matches

### Step 3: Cross-check every identifier you wrote

Each backticked identifier added in steps 1-2 must exist in the repo:

```
rg -l "marker_hover" tests/ config/ | head -2
rg -n "marker_stable" src/core/ros_px4_template_core/lib/mission/guards.py
rg -n "/drone/odom" docs/TOPICS.md
rg -n "vision" tasks.py | rg -- "--vision"
```

**Verify**: every grep above returns at least one match.

### Step 4: Full gate

**Verify**: `just check` -> exit 0 (docs are outside the lint scope; this
confirms nothing else was touched).

## Test plan

Doc-only; the Done-criteria greps are the machine checks. No unit tests.

## Done criteria

- [ ] `rg -n "hover_marker|enable_vision|/vision/marker_pose|sim_pose_adapter|px4_pose_adapter|default 3s" AGENTS.md docs/FRAMES.md` -> no matches
- [ ] `rg -n "sim headless" AGENTS.md` -> no matches
- [ ] `rg -n "marker_hover" AGENTS.md` -> at least one match (the corrected row)
- [ ] `rg -n "/drone/odom" docs/FRAMES.md` -> at least one match
- [ ] `git status` shows only `AGENTS.md` and `docs/FRAMES.md` modified
- [ ] `plans/README.md` status row updated

## STOP conditions

- The cited lines in AGENTS.md do not match the excerpts (drift).
- A grep in Step 3 finds that a "ground truth" identifier named here does not
  exist (this plan's facts have drifted; report instead of improvising).

## Maintenance notes

- This is the third doc-drift fix in this file's history (plans 001, 017).
  The underlying cause is prose duplicating code facts. If it drifts again,
  consider a drift-check script that greps AGENTS.md backticked identifiers
  against the codebase (deferred; noted for the maintainer).
- Reviewer: check the house style - no em dashes, no Unicode arrows.
