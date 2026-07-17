# Plan 054: Sub-second mission verification — engine-level simulation of the real mission YAMLs

> **Executor instructions**: Follow this plan step by step, verifying each
> step. On any STOP condition, stop and report. When done, update
> `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 01f94c7..HEAD -- src/core/ros_px4_template_core/lib/mission/ config/missions/ tests/unit/test_mission_engine.py tools/mission_cli.py docs/MISSIONS.md`
> On any mismatch with the excerpts below, STOP.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: LOW (purely additive test infrastructure; no runtime code changes)
- **Depends on**: none. Land BEFORE plan 059 (which changes engine
  self-transition semantics) so 059 inherits the harness for its own tests.
- **Category**: tests / dx
- **Planned at**: commit `01f94c7`, 2026-07-10

## Why this matters

The repo's stated goal is that an agent gets ARBITRARY new missions working
and verified quickly. Today the verification ladder has a hole in its most
important rung: `just mission validate` proves a mission YAML *parses*
(structure, known behaviors/guards, valid edges), and `just scenario`/e2e
proves it *flies* — but costs a 30s+ sim boot per attempt. Nothing in between
proves the graph actually *progresses*: that the happy path walks
takeoff → … → terminal, that guards fire when their conditions occur, that a
typo'd param means the mission stalls forever in `takeoff`.

The engine is already a pure function over an `Inputs` snapshot
(`tick(ctx, mission, inputs) -> Command`), and `tests/unit/test_mission_engine.py`
already ticks hand-built missions against scripted inputs. This plan turns
that pattern into a reusable `simulate()` harness with a tiny kinematic model,
applies it to EVERY real mission in `config/missions/`, and exposes it as
`just mission sim <name>` so an agent's edit→verify loop for mission logic
drops from ~30 s to <1 s.

## Current state

- Engine: `src/core/ros_px4_template_core/lib/mission/engine.py` —
  `tick(ctx: MissionContext, mission: Mission, inputs: Inputs) -> Command`;
  one transition max per tick; safety tier first; behaviors read/write
  per-state `ctx.scratch`; transition events appended to `ctx.events`.
- Inputs: `lib/mission/types.py` `Inputs` — fields visible in the test
  helper at `tests/unit/test_mission_engine.py:14-36` (`now, pose_enu,
  yaw_enu, armed, altitude_ok, estimate_ok, detections,
  detection_stability, input_ages, battery_remaining, failsafe_active`).
- Commands: `lib/mission/commands.py` — `GoTo(x, y, z, yaw)` and `Land()`.
- Existing engine-sim precedent: `tests/unit/test_mission_engine.py:121-158`
  (`test_reentry_reinitializes_descend_scratch_from_current_altitude`) —
  hand-scripted per-tick inputs; this plan generalizes exactly this.
- Loader: `lib/mission/loader.py:71-74` `load_mission_file(path)`; the six
  real missions are `config/missions/{demo,hover,marker_hover,precision_land,search_relocalize,yaw_demo}.yaml`.
  Only `tests/unit/test_mission_cli.py:59` loads a real file today (hover, structure only).
- CLI home: `tools/mission_cli.py` — typer app with `list/validate/show/schema`;
  `mission_path(name)` resolves names (`:34-44`); `just mission` forwards to it.
- Behavior semantics you must respect in the kinematic model (from
  `lib/mission/behaviors.py`): `hold`/`follow_waypoints` compare
  `math.dist(inputs.pose_enu, target) <= tolerance_m` and dwell `hold_s`
  (default 2.0 s); `center_land` descends only while a detection of
  `target_id` is fresh (`marker_fresh_s`, default 1.0) AND centered, and
  emits `Land()` at `land_altitude_m`; `armed_at_altitude` needs
  `armed and altitude_ok`.

## Commands you will need

| Purpose | Command | Expected |
|---------|---------|----------|
| Quality gate | `just check` | exit 0 |
| Targeted | `uv run pytest tests/unit/test_mission_sim.py -q` | all pass, <5 s |
| CLI smoke | `uv run tasks.py mission sim demo` | prints phase trace, exit 0 |

## Scope

**In scope**:
- `src/core/ros_px4_template_core/lib/mission/simulate.py` (new, rclpy-free)
- `tests/unit/test_mission_sim.py` (new)
- `tools/mission_cli.py` (new `sim` subcommand)
- `docs/MISSIONS.md` (document the new verification rung + CLI)
- `AGENTS.md` (one row in the verify-tier table)

**Out of scope**:
- `engine.py`, `behaviors.py`, `guards.py`, `loader.py` — read-only. If a real
  mission fails to progress under a fair input script, that's a FINDING to
  report (STOP condition), not something to "fix" by editing the engine.
- `mission_manager.py` — the ROS adapter is not exercised here (plan 057
  covers its `_snapshot`).
- Scenario/e2e infrastructure.

## Git workflow

- Branch: `advisor/054-mission-sim-harness`
- Commit style: `feat(mission): engine-level mission simulation (just mission sim)`

## Steps

### Step 1: The simulator (`lib/mission/simulate.py`)

Pure module (imports: `dataclasses`, `math`, mission lib only — NO rclpy,
matching the `lib/` rule in AGENTS.md). Core pieces:

```python
@dataclass
class SimResult:
    reached_states: list[str]      # in first-visit order
    final_state: str
    ticks: int
    terminated: bool               # reached a terminal state
    landed: bool                   # a Land command was emitted
    events: list[dict]             # accumulated ctx.events (TRANSITIONs etc.)

def simulate(
    mission: Mission,
    *,
    tick_rate_hz: float = 10.0,
    max_ticks: int = 3000,          # 300 sim-seconds at 10 Hz
    speed_m_s: float = 2.0,         # kinematic chase speed toward GoTo targets
    start_pose: tuple[float, float, float] = (0.0, 0.0, 0.0),
    script: Callable[[float, SimVehicle], None] | None = None,
) -> SimResult: ...
```

The kinematic model (`SimVehicle`) each tick:
- moves `pose_enu` toward the last `GoTo` target at `speed_m_s * dt`
  (straight-line; snap when closer than the step),
- `armed=True` once the first `GoTo` arrives (keep it simple; the FSM under
  test is the mission, not offboard arming),
- `altitude_ok = pose z >= takeoff_altitude - tolerance` — take the same
  defaults `mission_manager` declares (`takeoff_altitude_m=3.0`,
  `tolerance=0.3`, `mission_manager.py:78-79`); expose them as `simulate`
  kwargs,
- `input_ages={"odom": 0.0, "battery": 0.0, "vehicle_status": 0.0}`,
  `estimate_ok=True`, `battery_remaining=1.0`, `failsafe_active=False`
  (script hook can override any of these),
- detections: none by default; the `script(now, vehicle)` hook lets a test
  inject `vehicle.detections = (Detection(id=0, offset_body_flu=(dx, dy, dz), stamp=now),)`
  and `vehicle.detection_stability = {0: n}` — for marker missions the
  standard script plants a marker at a fixed world position and computes the
  body-FLU offset with `enu_offset_to_body_flu` from
  `lib/frames.py:129-139` (yaw 0 keeps it trivial: forward=east offset,
  left=north offset; the marker's `dz` = marker_z − drone_z),
- on a `Land()` command: descend at 0.5 m/s to z≤0.05, then set
  `armed=False` (models PX4 AUTO_LAND + auto-disarm so `disarmed` guards fire).

Loop: build `Inputs` from the vehicle, `tick()`, apply the command, record
first-visits and events, stop on terminal state or `max_ticks`.

**Verify**: `uv run pytest tests/unit/test_mission_engine.py -q` → still green
(nothing touched); `python -c "from ros_px4_template_core.lib.mission.simulate import simulate"`
via `uv run` → no import error (run from repo root; `tests/conftest.py`
already puts `src/core` on the path for pytest — for the direct import use
`uv run pytest` instead if the bare interpreter can't see the package).

### Step 2: Per-mission happy-path tests (`tests/unit/test_mission_sim.py`)

Parametrize over ALL `config/missions/*.yaml` via `load_mission_file` — glob
the directory so a future 7th mission is automatically covered (this is the
point: a NEW mission gets engine-sim coverage for free). Per mission, assert:

- `hover.yaml`: reaches its hold state; never terminates (no terminal set) —
  assert `final_state` is the hold state after `max_ticks≈200`.
- `demo.yaml`: `terminated=True`; `reached_states` includes each declared
  state in order (read the YAML in the test to derive the expectation, don't
  hardcode names that would drift).
- `yaw_demo.yaml`: `terminated=True`.
- `marker_hover.yaml`: with the marker script (marker at the search area),
  reaches its marker_hover state.
- `search_relocalize.yaml`: with the marker script, `terminated=True`.
- `precision_land.yaml`: with the marker script, `landed=True` and a
  disarm-driven exit — assert the `descend` state was visited and
  `terminated` per the YAML's terminal set.

Plus two negative tests that prove the harness catches real authoring errors:

- A mission dict whose only transition guard never fires (e.g. `hold` state
  with a `waypoints_done` guard) → `terminated=False` after `max_ticks` —
  the "stalls forever" failure an agent needs surfaced.
- `safety` diversion: run `demo.yaml` with a script that sets
  `estimate_ok=False` at t=5 s → `final_state == "hold_safe"`.
  (Note: as of `01f94c7`, `mission_manager` hardcodes `estimate_ok=True` at
  runtime — plan 050 fixes that — but the ENGINE honors the flag, which is
  what this harness tests.)

Read each mission YAML before writing its expectations — the state names
above come from `config/missions/` at `01f94c7`; derive, don't assume.

**Verify**: `uv run pytest tests/unit/test_mission_sim.py -q` → all pass in
< 5 s total. If a REAL mission fails under a fair script: STOP condition 2.

### Step 3: `just mission sim <name>`

Add a `sim` subcommand to `tools/mission_cli.py` (match the existing
`validate` command's shape, `:171-181`): load via `mission_path`/`load_mission_file`,
run `simulate()` with defaults (marker script auto-enabled when any state's
behavior name contains `marker`/`center` — keep the heuristic simple and
documented), then print a compact trace and verdict:

```
tick   0.0s  takeoff
tick   6.3s  takeoff -> follow      (armed_at_altitude)
tick  41.8s  follow  -> done        (waypoints_done)
OK demo: terminated in done after 41.8 sim-s (418 ticks)
```

Exit 0 on terminated (or on reaching steady state for terminal-less missions
— print which), exit 1 on stall (`max_ticks` without termination), matching
the repo's exit-code table (1 = ran but failed). `just mission` already
forwards args (justfile `mission *args`).

**Verify**: `uv run tasks.py mission sim demo` → OK line, exit 0.
`uv run tasks.py mission sim hover` → steady-state line, exit 0.

### Step 4: Docs

- `docs/MISSIONS.md`: add a "Simulating a mission (no sim boot)" subsection
  after the validate section, with the CLI example and the honest caveat: the
  kinematic model verifies GRAPH LOGIC (transitions, guards, stalls), not
  flight dynamics — the live scenario tier remains the flight gate.
- `AGENTS.md` Verify table: insert a row between Fast and Graph:
  `| Mission logic | just mission sim <name> | Nothing running |`.

**Verify**: `just check` → exit 0 (check_docs validates AGENTS.md tokens).

## Test plan

Step 2 IS the test plan: 6 happy-path parametrized cases + 2 negatives, all
under `tests/unit/test_mission_sim.py`, modeled structurally on
`tests/unit/test_mission_engine.py` (same import style, same `Inputs`
construction via the harness).

## Done criteria

- [ ] `uv run pytest tests/unit/test_mission_sim.py -q` → ≥8 tests, all pass, <5 s
- [ ] The parametrization GLOBS `config/missions/*.yaml` (adding a mission file adds a test)
- [ ] `uv run tasks.py mission sim demo` exit 0; stall case demonstrably exits 1 (temporarily point it at a stalling YAML in /tmp to check, don't commit it)
- [ ] `simulate.py` imports no rclpy (`grep -n rclpy src/core/ros_px4_template_core/lib/mission/simulate.py` → empty)
- [ ] `just check` exit 0
- [ ] `plans/README.md` row updated

## STOP conditions

1. `Inputs` has fields beyond those listed (types.py drifted) — update the
   harness to match, but if semantics are unclear, STOP.
2. A real mission in `config/missions/` fails to progress under a fair input
   script — that is a product finding, possibly a real mission bug. Report
   the trace; do NOT edit the mission YAML or engine to force a pass.
3. The marker-offset math produces geometrically impossible traces (drone
   never converges on the marker) — your body-FLU offset sign convention is
   wrong; re-read `frames.py:117-150` and `test_mission_engine.py:127`
   (`offset_body_flu=(0.0, 0.0, -5.0)` = marker 5 m BELOW the drone), then
   retry once; if still wrong, STOP.

## Maintenance notes

- Plan 059 changes safety self-transition semantics — its tests should be
  written WITH this harness; land 054 first.
- `just scenario-new` (plan 023) could later emit a matching engine-sim test
  stub next to the scenario stub — deferred, note it in the PR description.
- The kinematic model is intentionally crude (straight-line chase, instant
  arm). Anyone tempted to add dynamics should instead promote the case to the
  live scenario tier.
