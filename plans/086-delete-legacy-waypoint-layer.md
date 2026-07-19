# Plan 086: Delete the legacy waypoint layer + assorted confirmed-dead strays

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat d44126d..HEAD -- src/core/ros_px4_template_core/lib/waypoint_mission.py src/core/ros_px4_template_core/lib/mission_profile.py src/core/ros_px4_template_core/lib/mission/guards.py src/core/ros_px4_template_core/lib/mission/behaviors.py config/params/hardware.yaml pyproject.toml tools/gen_world.py tests/unit/test_waypoint_mission.py tests/unit/test_mission_profile.py`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none (no file overlap with 084/085/087/088)
- **Category**: tech-debt (dead code removal)
- **Planned at**: commit `d44126d`, 2026-07-18

## Why this matters

The repo carries a second, dead way to model waypoint missions
(`mission_profile.py` + the `reached`/`current_waypoint`/`WaypointMission`/
`MissionDefaults` half of `waypoint_mission.py`), kept alive solely by its
own unit tests — production waypoint following runs entirely through the
`lib/mission/` engine. A prior audit (plans/README.md, "Findings considered
and deferred") deferred this at ~36 LOC of payoff; two independent audits
have now re-confirmed it, and the payoff with tests is ~200 LOC and one
whole module. Riding along: three stranded `mission_manager` params in
`hardware.yaml` that the node silently ignores (a real hardware-tuning
trap), a test-only package (`tomli-w`) misfiled as a runtime dependency, a
literally-identical `if/else` in `gen_world.py`, and a duplicated
detection-selection loop in the mission engine.

## Current state

- `src/core/ros_px4_template_core/lib/waypoint_mission.py` (83 lines):
  - LIVE: `EnuPoint` (:14), `_point_from_dict` (:34), `_waypoints_from_raw`
    (:41), `load_path_yaml` (:48) — `lib/mission/loader.py:12` imports
    `load_path_yaml`; the engine parses inline waypoints via the same
    helpers.
  - DEAD: `MissionDefaults` (:21), `WaypointMission` (:28), `reached` (:59),
    `current_waypoint` (:79) — zero production importers; only
    `tests/unit/test_waypoint_mission.py` and `lib/mission_profile.py` use
    them. The live reach check is `lib/mission/behaviors.py`
    `follow_waypoints`' inline `math.dist(...) <= tol`.
- `src/core/ros_px4_template_core/lib/mission_profile.py` (37 lines): the
  whole module (`MissionProfileParams`, `build_mission_profile`) is imported
  only by `tests/unit/test_mission_profile.py` and
  `tests/unit/test_waypoint_mission.py`.
- `config/params/hardware.yaml:15-17`:
  ```yaml
  tolerance_m: 0.5
  z_tolerance_m: 0.0
  hold_s: 3.0
  ```
  under `mission_manager.ros__parameters` — but `mission_manager.py:67-72`
  declares only `log_dir`, `mission_file`, `tick_rate_hz`,
  `takeoff_altitude_m`, `takeoff_altitude_tolerance_m`, `marker_id`. The
  sibling `config/params/sim.yaml` was already cleaned of these keys (the
  2026-06-05 mission-FSM migration moved them into per-mission YAML);
  `hardware.yaml` was missed.
- `pyproject.toml:14`: `"tomli-w>=1.0"` sits in `[project].dependencies`;
  its only importer repo-wide is `tests/unit/test_capabilities.py:7`.
  Dev deps live in `[dependency-groups] dev = [...]` (pyproject.toml:21-22).
- `tools/gen_world.py:363-367` — both arms identical:
  ```python
  for i, marker in enumerate(markers):
      if i > 0:
          parts.append(_build_marker_include(marker))
      else:
          parts.append(_build_marker_include(marker))
  ```
- Duplicated detection-selection loop:
  - `lib/mission/guards.py:12-18` — `_fresh` iterates `inputs.detections`,
    skips `d.id != target_id`, tests `inputs.now - d.stamp <= t`.
  - `lib/mission/behaviors.py:14-21` — `_latest` iterates the same
    detections with the same id filter, keeping max `stamp`.
- Convention: `lib/` is rclpy-free pure logic (enforced by `lib/ruff.toml`);
  mission phase logic lives under `lib/mission/` (AGENTS.md invariant 5).

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Full gate | `just check` (host without ROS: `distrobox enter ubuntu -- bash -lc "just check"`) | exit 0 |
| Unit subset | `uv run pytest tests/unit -q` | all pass |
| Lint | `uv run ruff check src/ tools/ tests/` | exit 0 |
| gen_world golden | `uv run pytest tests/unit -q -k gen_world` | all pass (locks SDF output unchanged) |

## Scope

**In scope** (the only files you should modify/delete):
- Delete: `src/core/ros_px4_template_core/lib/mission_profile.py`,
  `tests/unit/test_mission_profile.py`
- Edit: `src/core/ros_px4_template_core/lib/waypoint_mission.py`,
  `tests/unit/test_waypoint_mission.py`,
  `src/core/ros_px4_template_core/lib/mission/guards.py`,
  `src/core/ros_px4_template_core/lib/mission/behaviors.py` (imports/one
  helper only), `config/params/hardware.yaml`, `pyproject.toml` (+ lockfile
  via `uv lock` if the repo tracks one), `tools/gen_world.py`,
  `plans/README.md` (status row)
- New (small): `src/core/ros_px4_template_core/lib/mission/detection.py`
  (or place the helper in `lib/mission/types.py` if `Detection` lives there
  — match wherever `Detection` is defined)

**Out of scope** (do NOT touch, even though they look related):
- `lib/mission/loader.py`, `lib/mission/engine.py`, `lib/mission/simulate.py`
  — live engine; only the import of `load_path_yaml` must keep resolving.
- The four C-grade functions Round 7 protected (`position_node._position_cb`,
  `loader.load_mission_dict`, `offboard_fsm.tick`, `behaviors.center_land`)
  — no restructuring beyond swapping in the shared detection helper.
- `config/params/sim.yaml` — already clean.
- Guard/behavior semantics: `_fresh` answers "any detection fresh within t";
  `_latest` answers "the newest detection". The shared helper must not merge
  those meanings.

## Git workflow

- Branch: `advisor/086-delete-legacy-waypoint-layer`
- Conventional commits, e.g. `refactor(lib)!: delete dead mission_profile/waypoint runtime`.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Delete the dead waypoint layer

Delete `mission_profile.py` and `test_mission_profile.py`. In
`waypoint_mission.py` delete `MissionDefaults`, `WaypointMission`,
`reached`, `current_waypoint` (keep `EnuPoint`, `_point_from_dict`,
`_waypoints_from_raw`, `load_path_yaml`; update the module docstring to
"Load ENU path geometry." since reachability evaluation leaves). In
`test_waypoint_mission.py` delete the imports of the removed symbols and the
test cases exercising them (`reached`, `current_waypoint`,
`build_mission_profile`); keep every `load_path_yaml` /
validation-error case.

**Verify**: `grep -rn "mission_profile\|MissionDefaults\|WaypointMission\|current_waypoint" src/ tools/ tests/ config/` → no matches (a bare `reached` grep will still hit the live `reached` mission guard in `guards.py` and mission YAMLs — that one is unrelated and stays); `uv run pytest tests/unit -q` → all pass.

### Step 2: Remove the stranded hardware params

Delete the three lines `tolerance_m: 0.5`, `z_tolerance_m: 0.0`,
`hold_s: 3.0` from `config/params/hardware.yaml`.

**Verify**: `grep -n "tolerance_m\|hold_s" config/params/hardware.yaml` →
only `takeoff_altitude_tolerance_m` remains (if present).

### Step 3: Move `tomli-w` to the dev group

Move `"tomli-w>=1.0"` from `[project].dependencies` to
`[dependency-groups].dev` in `pyproject.toml`; run `uv lock` if
`uv.lock` is tracked (check `git ls-files uv.lock`).

**Verify**: `uv run pytest tests/unit/test_capabilities.py -q` → all pass
(dev group still resolves).

### Step 4: Collapse the identical branch in `gen_world.py`

Replace lines 363-367 with:
```python
for marker in markers:
    parts.append(_build_marker_include(marker))
```

**Verify**: `uv run pytest tests/unit -q -k gen_world` → all pass (the
golden marker_field round-trip proves byte-identical output).

### Step 5: One detection-selection helper for guards and behaviors

Add to the module where `Detection` is defined (check
`lib/mission/types.py`; create `lib/mission/detection.py` only if `types.py`
would gain a function it stylistically shouldn't):

```python
def detections_for(detections: tuple[Detection, ...], target_id: int | None):
    """Detections matching target_id (all when target_id is None)."""
    return (d for d in detections if target_id is None or d.id == target_id)
```

Rewrite `guards._fresh` as
`return any(inputs.now - d.stamp <= t for d in detections_for(inputs.detections, target_id))`
and `behaviors._latest` as
`return max(detections_for(detections, target_id), key=lambda d: d.stamp, default=None)`.
Note `_latest` currently keeps the LAST max on stamp ties (`>=`); `max`
keeps the FIRST. If `tests/unit` pins tie behavior, preserve it (use
`max(..., key=lambda d: (d.stamp, i))` over `enumerate`, or keep the loop) —
check `tests/unit/test_mission_behaviors.py` first.

**Verify**: `uv run pytest tests/unit -q -k "guard or behavior or mission"` →
all pass.

### Step 6: Full gate

**Verify**: `just check` → exit 0 (includes colcon build — proves the
package still builds with the module deleted). Operator regression
sign-off if a sim is available: `just run 03_waypoint` → PASS (waypoint
following unaffected).

## Test plan

- Net-negative test change: `test_mission_profile.py` deleted; dead cases
  pruned from `test_waypoint_mission.py`. No new tests except: if Step 5's
  tie-behavior check finds NO existing pin for `_latest` ties, add one small
  case in `tests/unit/test_mission_behaviors.py` pinning whichever behavior
  you preserved.

## Done criteria

- [ ] `just check` exits 0
- [ ] `git ls-files src/core/ros_px4_template_core/lib/mission_profile.py` → empty
- [ ] `grep -rn "MissionDefaults\|WaypointMission" src/ tests/` → no matches
- [ ] `config/params/hardware.yaml` has no `tolerance_m:`/`z_tolerance_m:`/`hold_s:` keys
- [ ] `grep -n "tomli-w" pyproject.toml` → one match, inside the dev group
- [ ] `grep -n "i > 0" tools/gen_world.py` → no matches
- [ ] Exactly one detection-filter loop remains across `guards.py` + `behaviors.py`
- [ ] No files outside the in-scope list modified (`git status`)
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- Any production file (non-test, non-plan) imports a symbol this plan
  deletes.
- `just check`'s colcon build fails after deleting `mission_profile.py`
  (would indicate an entry-point or setup.py reference the audit missed —
  none exists at `d44126d`).
- Step 5 changes any guard/behavior test outcome — the helper must be
  behavior-neutral; report the failing test instead of adjusting semantics.
- The gen_world golden test fails after Step 4 (output must be
  byte-identical).

## Maintenance notes

- After this plan, `waypoint_mission.py` is purely "path-file geometry IO";
  if a later refactor wants it folded into `lib/mission/loader.py`, that's a
  rename-only follow-up (deliberately not done here to keep the diff
  reviewable).
- Reviewer focus: Step 5 tie-handling in `_latest`, and that
  `test_waypoint_mission.py` still covers malformed path files.
- The old deferral note in plans/README.md ("Findings considered and
  deferred") is superseded by this plan — the index update should say so.
