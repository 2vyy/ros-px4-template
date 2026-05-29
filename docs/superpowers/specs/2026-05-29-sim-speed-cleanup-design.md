# Sim Speed Flag + Bench Removal

**Date:** 2026-05-29

## Goal

Remove the warm-relaunch benchmark tooling (it served its purpose measuring the lifecycle
improvements and is no longer needed). Add a `--speed` flag to `just sim` so MCP/AI agents
can run headless scenario tests at accelerated physics without any hidden defaults or surprises.

## Removal

Delete entirely:
- `tools/bench_relaunch.py`
- `tests/unit/test_bench_relaunch.py`

Remove from `tasks.py`:
- The `bench()` command function and its `--fast-ekf2` option

Remove from `justfile`:
- The `bench *args` recipe and its comment

Everything else from the recent sim lifecycle work (`wait_ready.py`, `sim_cleanup.py`,
`sim_full.launch.py` XRCE persistence, preemptive world reset) stays — those are independently
useful and not specific to the bench tool.

## `--speed` Flag

### Interface

```
just sim bg --speed 4       # background, 4× physics — for agent scenario runs
just sim headless --speed 2 # foreground headless, 2× physics
just sim                    # GUI, 1× always (--speed ignored with warning)
just sim hardware            # real hardware, 1× always (--speed ignored with warning)
```

`--speed` is a float option on `tasks.py sim`, defaulting to `1.0`.

### Validation

- Reject values ≤ 0 immediately with a clear error before anything launches.
- Reject values > 20 with a clear error (unreasonable for any hardware running this stack).
- On `gui` or `hardware` modes: print a warning that `--speed` is ignored and continue at 1×.

### Implementation

In `sim_full.launch.py`, `_gz_px4_stack` receives the speed value via a new
`LaunchConfiguration("speed")`. After Gazebo is confirmed running (both cold-start and
warm-relaunch paths), call:

```
gz service -s /world/{world}/set_physics
  --reqtype gz.msgs.Physics
  --reptype gz.msgs.Boolean
  --timeout 3000
  --req "real_time_factor: {speed}, real_time_update_rate: {int(speed * 250)}, max_step_size: 0.004"
```

The `update_rate = int(speed * 250)` relationship holds because Gazebo's default step is 4ms
(250 Hz); 4× RTF requires 1000 Hz update rate.

If `speed == 1.0`, skip the call entirely (no subprocess, no side effects).

If the `gz service` call fails or times out, log a warning and continue — the sim runs at
whatever speed Gazebo defaulted to. This matches the existing pattern for non-fatal launch
errors.

### Why explicit, not a headless default

`--speed` is always opt-in. Headless and bg default to 1× identical to GUI. This is
intentional: the project standard is deterministic, explicit behavior. An agent passing
`--speed 4` is making a documented choice; if something breaks, the speed is never a hidden
variable. Hardware always runs at real time regardless of this flag.

## Agent Usage Pattern

The intended workflow for an MCP/AI agent running rapid scenario tests:

```
just sim bg --speed 4
just test scenario 01_arm_takeoff
just test scenario 02_hover_hold
just sim stop
```

No new justfile recipes. The existing `sim *args` passthrough handles everything.

## Testing

No new unit tests. The `--speed` path is verified by:
1. `just sim bg --speed 4` starts successfully
2. `just test scenario <name>` passes against a speed-4 sim

The correct check for physics accuracy is scenario correctness, not a unit test.
