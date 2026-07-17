# Plan 065: e2e at lockstep 2x with sim-time test timers (scenarios verify the exact same things)

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving on. On
> any STOP condition, stop and report. When done, update `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 4f56ebc..HEAD -- tools/wait_ready.py sim/launch/_start_gz_px4.sh tests/scenarios/_common.py tests/scenarios/02_hover_hold.py tests/scenarios/07_yaw_control.py tests/scenarios/08_precision_land.py`
> Plan 064 legitimately touches `tasks.py`; for THIS plan's `tasks.py` seams
> check only that `_e2e_run(configs, speed=...)` and the `e2e-worker --speed`
> option exist (from 064). On any other mismatch with the excerpts below, STOP.

## Status

- **BLOCKED (2026-07-11)**: Step 1 spike DISPROVED the plan's mechanism.
  Three spike rounds (see "Spike findings" below) established that ANY gz
  `set_physics` service call against the running stack latently corrupts
  PX4's altitude estimate: the call looks safe while disarmed (grounded z
  stable for 60 s), then the estimate runs away after arming (z to 10-24 km),
  regardless of payload (even values identical to the running physics) and
  regardless of speed (the 1x no-op call diverges the same as 2x). The
  "complete message" theory in Current state below is wrong; do not
  implement Steps 2+. The one still-plausible mechanism is 2x baked into
  the world SDF BEFORE boot (no call ever): at RTF 1.99 the vehicle armed
  and took off cleanly for the seconds before divergence set in, and a
  no-call boot is clean indefinitely. That path requires the repo world to
  actually be loaded, which is plan 049 (PX4's rcS/gz_env.sh clobbers
  PX4_GZ_WORLDS; the loaded world lives in PX4_DIR, invariant #3 forbids
  editing it). Re-plan on top of 049's pre-started-paused-gz boot rework.
- **Priority**: P1
- **Effort**: M (small diff, LIVE-heavy validation)
- **Risk**: MEDIUM (physics-speed history in this repo; mitigated by spike-first and a 1.0-equivalence gate)
- **Depends on**: 064 (worker `--speed` plumbing and polling workflow); NOW ALSO 049 (world boot handoff — see BLOCKED note)
- **Category**: dx / tests
- **Planned at**: commit `4f56ebc`, 2026-07-11
- **Spec**: `docs/superpowers/specs/2026-07-11-e2e-detach-and-speed-design.md` (untracked; docs/superpowers is gitignored)

## Why this matters

Profiled 2026-07-11: of the ~8 min e2e, ~4m10s is scenario flight time at
realtime. PX4 SITL runs in lockstep with Gazebo, and faster-than-realtime is
the standard, documented PX4 mechanism (PX4 docs: "Simulation speed factor").
At 2x, flight time halves; e2e lands near 5-5.5 min with zero verification
lost, IF the timers that define the assertions keep their meaning.

**HARD REQUIREMENT (from the user): scenarios must behave the exact same.**
A "30 s hover hold" must remain a 30-sim-second hold at every speed. The
strategy: durations that DEFINE behavior move to sim time (identical
semantics at any speed, robust even when the machine cannot sustain the
requested factor); durations that DETECT a dead stack stay wall-clock (a
wedged sim must still trip them). Equivalence is proven, not assumed: a full
e2e at speed 1.0 after the timer conversion must reproduce the recorded
baseline before any faster run counts.

## Current state (verify each excerpt before editing)

- **The env-var trap**: `sim/launch/_start_gz_px4.sh:25-34` — exporting
  `PX4_SIM_SPEED_FACTOR` at ANY value makes PX4's rcS
  (`px4-rc.gzsim:154-158`, verified in PX4 v1.17 tree: its gz `set_physics`
  request is only `"real_time_factor: ${PX4_SIM_SPEED_FACTOR}"`) send a
  Physics message whose unset `max_step_size` protobuf-defaults to 0,
  overwriting the world's 0.004 step -> integration blows up -> altitude
  runaway. Current guard only omits the export at exactly 1.0:

  ```bash
  if [ "$SIM_SPEED" != "1.0" ]; then
    export PX4_SIM_SPEED_FACTOR="$SIM_SPEED"
  fi
  ```

  So `--speed 2.0` is broken TODAY. This plan removes the export entirely:
  our own repair call is the only physics-speed writer.
- **The repair primitive already exists**: `tools/wait_ready.py:120-144`
  `_set_physics_speed(speed, world)` sends the COMPLETE message:

  ```python
  f"real_time_factor: {speed}, real_time_update_rate: {update_rate}, max_step_size: 0.004",
  ```

  with `update_rate = int(speed * 250)`. It is called at readiness
  (`:189-194`) for `speed != 1.0`, skipped at 1.0 (calling set_physics
  re-initialises the integrator; safe on the ground, dangerous airborne, see
  comment at `:183-188`). Validation at `:153-158` caps speed to `<= 1.0`
  (slow-motion only). `sim/worlds/default.sdf:5-6` confirms
  `max_step_size 0.004`, `real_time_factor 1.0`.
- **Readiness happens pre-arm**: readiness requires the GCS params flag;
  arming waits a further `arm_delay_s` (10 s in `config/params/sim.yaml`),
  so wait_ready's set_physics call lands while the vehicle is disarmed on
  the ground. The Step 1 spike confirms this live.
- `tasks.py` `sim()` (`:550-555`) validates `--speed` to `(0, 1.0]` and
  forces 1.0 with `--gui`; `wait_ready` is invoked with `--speed`/`--world`
  (`:601-614`). `_run_e2e_sim_group` hardcodes `"--speed", "1.0"`
  (`:830-840` region) and takes no speed parameter.
- **Core nodes are already sim-time**: `sim/launch/sim_full.launch.py:226`
  sets `"use_sim_time": "true"`; mission guards/freshness run on sim time.
  Only the TEST side is wall-clock.
- **Wall-clock timer audit of `tests/scenarios/` (complete list)**:
  - `_common.py` `Scenario.run` (`:156-192`): `timeout_s` via
    `asyncio.wait_for` + `elapsed` for reports. Both stay wall (timeout =
    dead-stack detector; elapsed = reporting only, and WILL shrink at 2x —
    expected, the e2e block prints wall seconds).
  - `02_hover_hold.py`: `_STABILIZE_S = 3.0` (behavior), `_HOLD_S = 30.0`
    (behavior), `_CLIMB_TIMEOUT_S = 180.0` (detector, stays wall),
    `_MAX_CONSEC_VIOLATIONS = 50` consecutive ~20 Hz wall-paced samples
    (~2.5 s of sustained drift; behavior-adjacent, converted to a
    2.5-sim-second continuous-violation window so the drift criterion is
    speed-invariant).
  - `07_yaw_control.py`: `_STABLE_S` in-band window at `:92-96` (behavior),
    `_ARM_FAIL_AFTER_S` never-left-ground early-exit at `:99-101` (detector,
    stays wall; at 2x the vehicle is airborne sooner, so the guard only gets
    more lenient), `timeout_s` (detector).
  - `08_precision_land.py`: `_FREEZE_HOLD_S` marker-withhold window at
    `:142-147` (behavior, and it INTERACTS with the mission engine's
    sim-time reacquire logic, so leaving it wall-clock at 2x would withhold
    the marker for twice the sim duration and could flip the mission into a
    different branch — this one is mandatory), plus wall `started`/elapsed
    (reporting).
  - `05_aruco_hover.py`, `06_search_relocalize.py`, `08`: synthetic-camera
    publishing via `create_timer(0.1, ...)` and header stamps from the node
    clock. With `use_sim_time` these scale automatically (10 Hz in sim time)
    which is exactly what keeps `marker_stable`/freshness guards equivalent:
    the mission engine counts frames and ages in sim time.
  - `06_search_relocalize.py` `run()` (`:159-219`): only wall
    elapsed/timeout (detectors). `01`, `03` (and `05`'s `run`): only
    `Scenario`-base or elapsed/timeout wall usage. No other behavior timers
    (re-verify: `rg -n "monotonic|create_timer" tests/scenarios/`).
- **Recorded 1x baseline** (2026-07-11 run, commit `4f56ebc`), the
  equivalence yardstick:

  ```
  PASS 01_arm_takeoff   z_enu=2.99                                   32.1s
  PASS 02_hover_hold    violations=0                                 51.2s
  PASS 03_waypoint      waypoints_done=0, phase=done                 30.3s
  PASS 05_aruco_hover   ok                                           28.4s
  PASS 06_search_reloc  override_count=260                           48.1s
  PASS 07_yaw_control   setpoint_yaw_err=0.0, vehicle_yaw_err=0.01   22.5s
  PASS 08_precision_land xy_err=0.06m, froze+reacquired+landed       37.1s
  ```

## Commands you will need

| Purpose | Command | Expected |
|---------|---------|----------|
| Quality gate | `just check` | exit 0 |
| Timer helper tests | `uv run pytest tests/unit/test_sim_clock.py -q` | all pass |
| Spike / live runs (operator) | see Steps 1, 5, 6 | clean hover; 7/7 PASS |

## Scope

**In scope**:
- `tools/wait_ready.py` (lift the speed cap; messages/comments)
- `sim/launch/_start_gz_px4.sh` (delete the conditional export; comment)
- `tasks.py` (`sim()` speed range; `_run_e2e_sim_group` speed param;
  `test e2e --speed` -> worker -> `_e2e_run`)
- `tests/scenarios/_common.py` (sim-time helpers), scenarios 02, 07, 08
  (behavior timers to sim time), 05/06/08 nodes (`use_sim_time`)
- `tests/unit/test_sim_clock.py` (new)
- `AGENTS.md` (speed flag row; timer policy sentence)

**Out of scope**:
- `arm_delay_s` and readiness polling (plan 055's territory)
- Parallel sim groups (future plan; deferred by design)
- Flipping the e2e DEFAULT speed to 2.0 (only after the Step 6 gate, and as
  its own final commit that can be reverted alone)
- PX4/Gazebo sources (invariant; we only call the public gz service)

## Git workflow

- Branch: `advisor/065-e2e-speed-factor`
- Commit style: `feat(sim): safe faster-than-realtime physics; sim-time scenario timers`
- Separate final commit for the default flip (if reached):
  `feat(e2e): default e2e speed 2.0 after 3x clean validation`

## Steps

### Step 1: Spike — prove 2x physics is clean BEFORE writing code (operator)

No repo edits. Boot a plain sim, set physics 2x by hand pre-arm, fly the two
most speed-sensitive scenarios against it:

```bash
just sim                       # disarmed, speed 1.0, no overlay
gz service -s /world/default/set_physics --reqtype gz.msgs.Physics \
  --reptype gz.msgs.Boolean --timeout 2000 \
  --req "real_time_factor: 2.0, real_time_update_rate: 500, max_step_size: 0.004"
uv run python tests/scenarios/01_arm_takeoff.py     # arms itself
just stop && just sim
gz service ... (same set_physics)
uv run python tests/scenarios/02_hover_hold.py
just stop
```

Expected: both PASS; `rg "runaway|RUNAWAY|failsafe" logs/latest.log` clean;
02's hold is solid (violations=0; note the hold takes ~15 wall seconds
because its 30 s timer is still wall-clock at this point — that asymmetry is
what Steps 3-4 fix). Watch CPU (`top`) during the run: if the machine cannot
hold real_time_factor 2.0 headless, note the achieved factor.

**STOP conditions for this step**: altitude runaway, EKF divergence, or
either scenario FAILs for a physics-looking reason. Report findings; the
rest of the plan is void without a clean spike.

### Step 2: Lift the artificial speed ceiling (the guard moves, it does not weaken)

`tools/wait_ready.py`: change the validation (`:153-158`) to accept
`(0, 4.0]`:

```python
    if speed <= 0 or speed > 4.0:
        typer.echo(
            f"Error: --speed must be in (0, 4.0], got {speed}",
            err=True,
        )
        sys.exit(1)
```

Update the option help to `"Physics speed factor (1.0 = realtime; != 1.0
applied via set_physics at readiness, pre-arm)"` and rewrite the `:183-188`
comment block: the set_physics call now serves BOTH slow-motion and
faster-than-realtime; it stays skipped at exactly 1.0 for the documented
integrator-reinit reason; it always runs pre-arm (readiness precedes
`arm_delay_s`).

`sim/launch/_start_gz_px4.sh`: DELETE the `if [ "$SIM_SPEED" != "1.0" ]`
export block. Replace the `# CRITICAL:` comment with:

```bash
# CRITICAL: never export PX4_SIM_SPEED_FACTOR. PX4's rcS (px4-rc.gzsim) would
# call gz set_physics with only real_time_factor set, so max_step_size
# protobuf-defaults to 0, zeroing the world's 0.004 step: physics integration
# blows up and the vehicle climbs away uncontrollably after arming (the
# altitude "runaway"). Speed != 1.0 is applied instead by tools/wait_ready.py
# at readiness (pre-arm) via a COMPLETE set_physics message (real_time_factor,
# real_time_update_rate, max_step_size). SIM_SPEED is still passed in for
# wait_ready's caller; this script must not act on it.
```

`tasks.py` `sim()`: relax `:550-552` to the same `(0, 4.0]` range and update
the option help (`"Gazebo physics speed (0-4x; !=1.0 headless only)"`). Keep
the `--gui` force-to-1.0.

**Verify**: `just check` -> exit 0. Then live (operator):
`just sim --speed 2.0` -> READY verdict includes the wait_ready line
`[OK] Gazebo physics speed throttled to 2.0x` (reword that message to
`set to {speed}x` while there — "throttled" is wrong for >1);
`uv run python tests/scenarios/01_arm_takeoff.py` -> PASS; `just stop`.

### Step 3: Sim-time helpers in `_common.py` + unit tests (TDD)

Create `tests/unit/test_sim_clock.py` FIRST:

```python
"""Unit tests for the sim-time window helper used by live scenarios."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tests" / "scenarios"))

from _common import SimWindow


def test_window_elapses_with_injected_clock() -> None:
    t = [100.0]
    w = SimWindow(now_fn=lambda: t[0])
    w.start()
    assert not w.elapsed(5.0)
    t[0] = 104.9
    assert not w.elapsed(5.0)
    t[0] = 105.0
    assert w.elapsed(5.0)


def test_window_reset_restarts_the_clock() -> None:
    t = [0.0]
    w = SimWindow(now_fn=lambda: t[0])
    w.start()
    t[0] = 10.0
    w.start()  # restart
    assert not w.elapsed(5.0)
    t[0] = 15.0
    assert w.elapsed(5.0)


def test_window_not_started_never_elapses() -> None:
    w = SimWindow(now_fn=lambda: 50.0)
    assert not w.elapsed(0.0)
```

Run: `uv run pytest tests/unit/test_sim_clock.py -q` -> FAIL (ImportError).
(`tests/unit/test_scenario_imports.py` already imports scenario modules, so
rclpy availability in the unit env is established.)

Then add to `tests/scenarios/_common.py`:

```python
def enable_sim_time(node: Node) -> None:
    """Put a scenario node on /clock (Gazebo sim time), matching the core nodes.

    Behavior durations measured through this clock mean the same thing at any
    physics speed factor. Failure timeouts must stay wall-clock so a wedged
    sim still trips them.
    """
    node.set_parameters([rclpy.parameter.Parameter("use_sim_time", value=True)])


def sim_now(node: Node) -> float:
    """Current sim time in float seconds from the node clock."""
    return node.get_clock().now().nanoseconds * 1e-9


class SimWindow:
    """A restartable duration window over an injectable clock.

    `now_fn` is `lambda: sim_now(node)` in scenarios; tests inject a fake.
    """

    def __init__(self, now_fn: Callable[[], float]) -> None:
        self._now_fn = now_fn
        self._started_at: float | None = None

    def start(self) -> None:
        self._started_at = self._now_fn()

    def clear(self) -> None:
        self._started_at = None

    @property
    def running(self) -> bool:
        return self._started_at is not None

    def elapsed(self, duration_s: float) -> bool:
        if self._started_at is None:
            return False
        return self._now_fn() - self._started_at >= duration_s
```

(`rclpy.parameter` import: `rclpy` is already imported; use
`rclpy.parameter.Parameter("use_sim_time", value=True)` — verify the
constructor accepts the value kwarg on Jazzy; if not, use
`Parameter("use_sim_time", Parameter.Type.BOOL, True)`.)

Run: `uv run pytest tests/unit/test_sim_clock.py -q` -> 3 passed. Commit.

### Step 4: Convert the behavior timers (and ONLY the behavior timers)

For each file, call `enable_sim_time(node)` immediately after constructing
the node (before any timer/state logic), then convert:

- **`02_hover_hold.py`** (`run()` at `:44-130`): after `node = _Node()`,
  `enable_sim_time(node)`. Replace the three behavior timers:

  ```python
  stabilize = SimWindow(now_fn=lambda: sim_now(node))
  stabilize.start()
  await spin_until(node, lambda: stabilize.elapsed(_STABILIZE_S))
  ```

  ```python
  hold = SimWindow(now_fn=lambda: sim_now(node))
  hold.start()
  violation = SimWindow(now_fn=lambda: sim_now(node))
  drift_failed = [False]

  def hold_ok() -> bool:
      if hold.elapsed(_HOLD_S):
          return True
      dx = abs(node.x - anchor[0])
      dy = abs(node.y - anchor[1])
      dz = abs(node.z - anchor[2])
      if dx > _XY_TOL or dy > _XY_TOL or dz > _ALT_TOL:
          if not violation.running:
              violation.start()
          if violation.elapsed(_MAX_DRIFT_S):
              drift_failed[0] = True
              return True
      else:
          violation.clear()  # reset on recovery — transient spikes don't accumulate
      return False
  ```

  with `_MAX_DRIFT_S = 2.5` replacing `_MAX_CONSEC_VIOLATIONS = 50` (the
  constant's comment already defines it as "~2.5 s of sustained drift"; the
  window makes that definition exact and speed-invariant). Post-hold checks:
  `drift_failed[0]` replaces `consec_violations > _MAX_CONSEC_VIOLATIONS`;
  `hold_elapsed` for the `hold_too_short` check becomes sim-time
  (`sim_now(node) - hold_started_sim`, captured next to `hold.start()`).
  Keep `_CLIMB_TIMEOUT_S` on `asyncio.wait_for` (wall). Report detail: keep
  a `violations` key for continuity but document it now reports
  `drift_failed` boolean semantics, or rename to `drift_failed` and accept
  the detail-string change (pick renaming; the e2e block prints details
  verbatim and honesty beats continuity).
- **`07_yaw_control.py`**: `enable_sim_time(node)` after construction.
  `_in_band_since` list becomes `in_band = SimWindow(now_fn=lambda:
  sim_now(node))`: on both-ok, `if not in_band.running: in_band.start()`
  `elif in_band.elapsed(_STABLE_S): return True`; on not-ok `in_band.clear()`.
  `_ARM_FAIL_AFTER_S` early-exit and `timeout_s` stay wall-clock as-is.
- **`08_precision_land.py`**: `enable_sim_time(self)` inside `_Node.__init__`
  (its `create_timer(0.1, ...)` and image stamps then run on sim time).
  `_freeze_start_time` becomes a `SimWindow` started in `_status_cb`
  (`self._freeze = SimWindow(now_fn=lambda: sim_now(self))`); the `:142-147`
  check becomes `if self._loss_stage == "frozen_hold" and
  self._freeze.elapsed(_FREEZE_HOLD_S):`.
- **`05_aruco_hover.py`, `06_search_relocalize.py`**: `enable_sim_time` on
  the node (publishers/stamps scale); no other timer changes (their
  monotonic uses are detectors/reporting only — confirm against the audit
  with `rg -n "monotonic" tests/scenarios/05_aruco_hover.py
  tests/scenarios/06_search_relocalize.py`).
- **`_common.py` `Scenario`**: `run()` calls `enable_sim_time(node)` right
  after `make_node()`. `timeout_s` and report `elapsed` stay wall.

**Verify**: `just check` -> exit 0 (imports + lint; scenario logic is
live-verified next).

### Step 5: THE EQUIVALENCE GATE — full e2e at 1.0 must reproduce the baseline

Live (operator), with 064 landed: `just test e2e` (speed 1.0 default), poll
`just e2e-status` to completion.

Required: 7/7 PASS and per-scenario details equivalent to the recorded
baseline (see Current state): 02 completes its full 30 s hold with no drift
failure; 06 `override_count` same order of magnitude (hundreds); 07 yaw
errors <= tolerance as before; 08 froze/reacquired/landed all true with
xy_err ~0.05-0.1 m; wall elapsed within ~±20% of baseline per scenario
(nothing should get faster or slower at 1.0).

**STOP condition**: any scenario fails or a detail departs from baseline
beyond the stated bands. The timer conversion changed behavior at 1.0 —
that violates the hard requirement. Fix or revert before touching speed.

Run it TWICE. Both clean -> commit.

### Step 6: Thread `--speed` through e2e, then the 3-run validation at 2.0

`tasks.py` (seams created by 064):

- `test(...)` gains `speed: float = typer.Option(1.0, "--speed",
  help="e2e only: physics speed factor (validated at 2.0).")`; the e2e
  branch passes it to the worker spawn
  (`[..., "e2e-worker", "--speed", str(speed)]`) and to `_e2e_run(configs,
  speed=speed)` on the `--wait` path. Validate `(0, 4.0]` like `sim()`.
- `_run_e2e_sim_group(...)` gains `speed: float = 1.0`; replace the
  hardcoded `"--speed", "1.0"` in its wait_ready invocation with
  `str(speed)`, and pass `f"speed:={speed}"` in `launch_args` alongside the
  existing args (launch forwards SIM_SPEED; the script ignores it by design
  after Step 2). `_e2e_run` forwards its `speed` to every group call.
- `e2e-status` (tools/e2e_status.py): include `at {speed}x` in the RUNNING
  line when `state["speed"] != 1.0` (extend one existing unit test to cover
  the string).

**Verify**: `just check` -> exit 0. Then the validation protocol (operator):
run `just test e2e --speed 2.0` THREE times, polling to completion, `just
stop` between runs. Required for EACH run: 7/7 PASS; 02 full hold, no drift
fail; 08 froze/reacquired/landed; 06 override_count hundreds; total wall
time meaningfully below the 1.0 runs (expect ~5-6 min vs ~8). Record the
three report blocks in the commit message or `plans/README.md` notes.

**STOP condition**: any of the three runs fails or flakes. Report the
failing scenario + `logs/latest.log` extract; do NOT proceed to Step 7. The
plan still lands through Step 5 (opt-in `--speed` stays available for
experimentation, default remains 1.0).

### Step 7: Flip the e2e default (own commit, only if Step 6 was 3/3 clean)

Change the `test` command's speed default to `2.0` (e2e branch only — guard
so `unit`/`scenario` types ignore it), update the STARTED line's estimate
formula from `n * 65` to `n * 45` seconds, and document in AGENTS.md:
"`just test e2e` runs physics at 2x (lockstep; validated); pass
`--speed 1.0` to reproduce realtime timing." Commit separately:
`feat(e2e): default e2e speed 2.0 after 3x clean validation`.

**Verify**: `just check`; one more full `just test e2e` (now defaulting
2.0) -> 7/7 PASS.

### Step 8: Docs

`AGENTS.md`: sim flags line gains the new speed range; add one sentence to
the scenario-authoring bullet: "Behavior durations (holds, stability
windows) use `SimWindow`/`sim_now` from `_common.py` (sim time); failure
timeouts stay wall-clock." `README.md`: mirror the flag change if the sim
flags are listed there.

**Verify**: `just check` -> exit 0.

## Done criteria

- [ ] Spike proved clean 2x physics pre-arm (01 + 02 PASS at manual 2x)
- [ ] `PX4_SIM_SPEED_FACTOR` never exported (`rg PX4_SIM_SPEED_FACTOR sim/` shows only the warning comment)
- [ ] `just sim --speed 2.0` reaches READY and 01 passes against it
- [ ] Equivalence gate: post-conversion e2e at 1.0, twice, 7/7 PASS with baseline-equivalent details
- [ ] 3 consecutive `just test e2e --speed 2.0` runs 7/7 PASS, wall time ~5-6 min
- [ ] Default flipped only after the 3/3 gate (else default stays 1.0 and that is recorded)
- [ ] `uv run pytest tests/unit/test_sim_clock.py -q` passes; `just check` exit 0
- [ ] `plans/README.md` row updated

## STOP conditions

- Step 1 spike shows runaway/EKF divergence at 2x: report and stop (the
  whole plan is predicated on clean lockstep 2x on this machine).
- Step 5 equivalence gate fails: the conversion changed 1.0 behavior; stop.
- The machine cannot sustain ~2x real-time factor headless (watch achieved
  RTF in the spike): cap ambitions at the achieved factor or stop; do not
  ship a default the hardware cannot hold.
- `wait_ready`'s readiness-precedes-arming assumption is violated (a group's
  overlay arms before the GCS params flag): visible as set_physics landing
  post-arm in `logs/latest.log` ordering; stop and report.

## Maintenance notes

- The sim-time/wall-clock split is the invariant to protect in review:
  behavior durations = sim time; dead-stack detectors = wall. New scenarios
  get this via the AGENTS.md sentence and `SimWindow` being the obvious tool.
- Parallel sim groups (the other 2-3x, machine-permitting) remain future
  work; profile first on >16 GiB hardware.
- If a future PX4 bump fixes px4-rc.gzsim's partial set_physics message,
  the no-export rule in `_start_gz_px4.sh` is still correct (our repair call
  is idempotent and complete); do not reintroduce the env var.

## Spike findings (2026-07-11, three rounds, branch advisor/065-e2e-speed-factor, no code landed)

Truth table (scenario 01 unless noted; z values are /drone/odom ENU, a direct
conversion of PX4's vehicle_local_position, so divergence is PX4's estimator):

| set_physics call | vehicle state at call | flight speed | outcome |
|---|---|---|---|
| none | any | 1x | clean (e2e 7/7; idle z stable indefinitely) |
| complete 2x values | flying | 2x | z runaway (269 m -> 18,849 m) |
| complete no-op 1x values | flying | 1x | z runaway (48 m -> 231 m) |
| complete 2x values | disarmed, grounded | 2x | grounded z stable ~60 s; runaway after arming (23,698 m) |
| complete no-op 1x values | disarmed, grounded | 1x | grounded z stable; runaway after arming (11,166 m) |

Facts established:

1. The poison is the set_physics CALL itself, unconditional on payload,
   vehicle state, and speed; it is latent until thrust is applied. The old
   root-cause story (max_step_size protobuf-defaulting to 0) was incomplete:
   a COMPLETE message with max_step_size 0.004 diverges identically.
   Corollary: tools/wait_ready.py's slow-motion set_physics path
   (speed < 1.0) is latently broken too and should be removed or refused.
2. 2x physics itself is NOT the problem: at achieved RTF 1.99 the vehicle
   armed cleanly and took off to 2.79 m before the call-induced divergence
   set in. 2x-from-boot (never calling set_physics) remains plausible.
3. The repo world SDF is inert: boot loads
   PX4_DIR/Tools/simulation/gz/worlds/default.sdf (rcS/gz_env.sh clobbers
   PX4_GZ_WORLDS; plan 049). So 2x-from-boot cannot be tested or shipped
   until 049's boot handoff lands. Achieved RTF measured via /clock deltas
   (gz stats topic echoes nothing on this setup).
4. Incidental doc drift found: config/params/sim.yaml sets auto_arm: true,
   so a plain `just sim` arms itself ~10 s after XRCE connect and flies the
   demo mission — AGENTS.md says "boots disarmed by default". This also
   makes scenario 01's warm_start guard fire on any boot older than ~30 s.
   Feed into plan 060 (doc drift) or fix the config/doc mismatch directly.
5. Sim health check gap: nothing in readiness or scenario plumbing notices
   a diverged estimator on an idle stack (z can hit kilometers silently).
   A cheap post-arm sanity assert (z within physical bounds) would have
   caught every runaway variant early.
