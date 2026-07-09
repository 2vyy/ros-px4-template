# Missions

A mission is **data, not code**: a YAML graph of *states* and *transitions* that a
tiny pure engine (`lib/mission/engine.py`) interprets one tick at a time. Each
state names a **behavior** (what to do) and each transition names a **guard**
(when to move). Behaviors and guards are small pure functions registered by
name, so a new mission is usually just a new YAML file — no node changes.

- Engine + library: `src/core/ros_px4_template_core/lib/mission/`
- Mission files: `config/missions/*.yaml`
- Runner node: `mission_manager` (`nodes/mission_manager.py`)

## Selecting a mission

`mission_manager` reads the `mission_file` parameter (relative to the project
root). Point it at a mission via a params overlay, e.g.
`config/params/overlays/search_relocalize.yaml`:

```yaml
offboard_controller:
  ros__parameters:
    auto_arm: true
mission_manager:
  ros__parameters:
    mission_file: "config/missions/search_relocalize.yaml"
```

## File format

```yaml
mission:
  initial: <state name>           # state the engine starts in
  safety:                         # optional global transitions, see below
    - {guard: <name>, params: {...}, to: <state>}
  states:
    <name>: {behavior: <name>, params: {...}}
    ...
  transitions:                    # per-state transitions
    - {from: <state>, guard: <name>, params: {...}, to: <state>}
    ...
  terminal: [<state>, ...]        # optional; states with no outgoing mission edges
```

The loader (`lib/mission/loader.py`) validates the document up front and raises
`MissionError` for an unknown behavior, guard, initial state, or transition
target — a malformed mission fails fast at startup, not mid-flight.

## Validate from the CLI

The loader is `rclpy`-free, so the same validation is reachable without booting
anything. `just mission` runs in under a second on a bare checkout (no ROS, no
build, no sim):

```bash
just mission list                 # every config/missions/*.yaml with its description
just mission validate <name>      # OK / FAIL with the exact loader error; exit 2 on failure
just mission show <name>          # states, transitions, and terminal set of a loaded mission
```

`just mission validate hover` runs the identical loader `mission_manager` uses at
runtime, so a misspelled behavior or a transition to a nonexistent state surfaces
here instead of after a ~16-30s Gazebo + PX4 SITL boot.

## Editor schema

Each `config/missions/*.yaml` starts with a `# yaml-language-server: $schema=...`
directive pointing at `schemas/mission.schema.json`, so a schema-aware editor
(VS Code / Neovim / Cursor YAML extensions) gives autocomplete for `behavior` and
`guard` names and flags structural mistakes as you type. The schema is generated
from the registry (`known_behaviors()` / `known_guards()`), never hand-edited:
regenerate it with `just mission schema > schemas/mission.schema.json` whenever a
behavior or guard is added or removed. A unit test fails if the committed file
drifts from the registry.

## FSM semantics (this is a real FSM, not a switch statement)

Each tick (`tick_rate_hz`, default 10 Hz) the engine:

1. Builds an **immutable `Inputs` snapshot** (pose, arm/altitude/estimate flags,
   detections, input ages). Behaviors and guards only ever see this snapshot, so
   a value cannot change underneath them mid-tick — this is what keeps
   transitions race-free.
2. Runs the **current state's behavior** to produce a `Command`
   (`GoTo` / `Hold` / `Land`) and a dict of **signals**.
3. Evaluates the **`safety` tier first** (every tick, from any state, including
   terminal states), then — only if the current state is not terminal — the
   per-state **`transitions`** whose `from` matches the current state.
4. Fires **at most one transition per tick** (first matching guard wins, in file
   order; safety always outranks mission transitions). On a fire it logs a
   structured `TRANSITION` event (from, to, guard, trigger values), clears the
   scratch of both states so the new state enters fresh, and re-runs the new
   state's behavior so the entry command is emitted the same tick.

Because `safety` is checked before the per-state edges, a hazard always wins over
normal progression. Example from `search_relocalize.yaml`: while flying a
lawnmower `search`, if `geofence_breach` trips it diverts to `return_to_origin`
instead of continuing the pattern — exactly the non-linear behavior a search
mission needs.

### Terminal states

States listed in `terminal` have no outgoing **mission** transitions evaluated,
but the **safety** tier still runs — a terminal `done` that holds position will
still bail out to a safe state if the estimate goes invalid.

## Behaviors

Registered in `lib/mission/behaviors.py`. Each returns a command plus signals
(read by guards). `params` keys and defaults:

| Behavior | params (default) | Signals emitted |
|----------|------------------|-----------------|
| `hold` | `x`,`y`,`z` (current pose at entry), `yaw_deg` (optional, ENU degrees, latched at entry), `tolerance_m` (0.4) | `reached` |
| `follow_waypoints` | `waypoints` (list of `[x,y,z]` or `[x,y,z,yaw_deg]`) **or** `path_file` (YAML path, resolved to waypoints by the loader), `tolerance_m` (0.4), `hold_s` (2.0) | `reached`, `waypoints_done`, `waypoint_index` |
| `search_lawnmower` | `center` (`[0,0]`), `spacing_m` (2.0), `legs` (4), `altitude_m` (3.0), `hold_s` (0.0) | `search_complete` |
| `center_on_marker` | `target_id`, `altitude_m` (current z), `tolerance_m` (0.4), `hold_s` (10.0) | `centering_error`, `centered`, `hold_complete` |
| `goto_origin` | `z` (current z), `tolerance_m` (0.5) | `reached` |

`path_file` is resolved relative to the project root and may be used anywhere
`follow_waypoints` accepts `waypoints`.

## Guards

Registered in `lib/mission/guards.py`. Each is a pure predicate over the snapshot
(and, for the signal guards, the current behavior's signals).

| Guard | params (default) | True when |
|-------|------------------|-----------|
| `armed_at_altitude` | — | vehicle armed **and** at/above takeoff altitude |
| `waypoints_done` | — | behavior signalled `waypoints_done` |
| `reached` | — | behavior signalled `reached` |
| `hold_complete` | — | behavior signalled `hold_complete` |
| `search_complete` | — | behavior signalled `search_complete` |
| `marker_fresh` | `id`, `t` (1.0) | a detection of `id` is newer than `t` s |
| `marker_stable` | `id`, `n` (5) | `id` seen on ≥ `n` consecutive fresh detections |
| `marker_lost` | `id`, `t` (3.0) | no detection of `id` within `t` s |
| `geofence_breach` | `radius_m` (50.0) | horizontal distance from origin ≥ `radius_m` |
| `estimate_invalid` | — | the state estimate is not OK |
| `inputs_stale` | `key` (`odom`), `t` (1.0) | named input older than `t` s |

For `marker_*` guards, omitting `id` matches any marker.

## Commanding yaw

`hold` and `follow_waypoints` accept an optional `yaw_deg` (ENU degrees, 0 =
East, positive counter-clockwise). Omitting it means heading is uncontrolled:
PX4 holds whatever heading it already has. When set, `GoTo.yaw` carries the
value as ENU radians through `mission_manager` to `offboard_controller`, which
is the only place ENU yaw is converted to PX4 NED heading (`/fmu/in/trajectory_setpoint`'s `yaw` field).

On the wire, `/drone/target_pose`'s orientation quaternion is the optional-yaw
contract: the all-zero quaternion is the internal sentinel for "yaw omitted"
(the identity quaternion is a real ENU yaw of zero, so it cannot double as the
sentinel); any other finite, near-unit quaternion is a commanded ENU yaw. See
`lib/target_pose.py` for the codec.

## Vision relocalization

When launched with `vision=aruco`, `aruco_pose_publisher` publishes
`/drone/marker_detection` and `marker_localizer` turns a detection of a **known**
marker (mapped in `config/markers.yaml`) into a `/drone/pose_override`
(`PoseStamped`). `position_node` applies that fix to the published `/drone/odom`
when it is fresh and within a jump bound — so a known marker can correct drift
without letting a bad fix teleport the vehicle. Missions consume the corrected
pose transparently; the `search_relocalize` mission demonstrates the full loop.

## Adding a behavior or guard

1. Write a pure function in `behaviors.py` / `guards.py` and decorate it with
   `@behavior("name")` / `@guard("name")`. Behaviors take
   `(scratch, inputs, params)` and return `BehaviorResult(command, signals)`;
   guards take `(inputs, signals, params)` and return `bool`.
2. Add a unit test in `tests/unit/test_mission_behaviors.py` /
   `test_mission_guards.py`.
3. Reference it by name from a mission YAML. The loader validates the name on
   load.

## Topics

| Topic | Role |
|-------|------|
| `/drone/mission_status` | Current phase (= engine state name) |
| `/drone/target_pose` | Setpoint to `offboard_controller` |
| `/drone/marker_detection` | Metric marker detections (vision) |
| `/drone/pose_override` | Known-marker relocalization fix |

Full manifest: [docs/TOPICS.md](TOPICS.md).

## Example: `search_relocalize.yaml`

```yaml
mission:
  initial: takeoff
  safety:
    - {guard: estimate_invalid, to: hold_safe}
    - {guard: inputs_stale, params: {t: 1.0}, to: hold_safe}
    - {guard: geofence_breach, params: {radius_m: 30.0}, to: return_to_origin}
  states:
    takeoff:          {behavior: hold, params: {z: 3.0}}
    search:           {behavior: search_lawnmower, params: {center: [0.0, 0.0], spacing_m: 8.0, legs: 2, altitude_m: 3.0}}
    return_to_origin: {behavior: goto_origin, params: {z: 3.0}}
    done:             {behavior: hold}
    hold_safe:        {behavior: hold}
  transitions:
    - {from: takeoff,          guard: armed_at_altitude,                    to: search}
    - {from: search,           guard: marker_stable, params: {id: 0, n: 5}, to: return_to_origin}
    - {from: search,           guard: search_complete,                      to: return_to_origin}
    - {from: return_to_origin, guard: reached,                              to: done}
  terminal: [done]
```

## Scenario coverage

| Scenario | Needs |
|----------|--------|
| `03_waypoint` | Default sim (`follow_waypoints` mission, no vision) |
| `05_aruco_hover` | `vision=aruco` (`marker_hover` mission) |
| `06_search_relocalize` | `vision=aruco` (`search_relocalize` mission + `marker_localizer`) |
| `07_yaw_control` | Overlay `yaw_demo` (`yaw_demo` mission, no vision) |
