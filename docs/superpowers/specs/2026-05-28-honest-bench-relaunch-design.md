# Honest Warm-Relaunch Benchmark

**Date:** 2026-05-28  
**Status:** Approved for implementation

---

## Problem

The "fast relaunch" optimization work introduced three problems:

1. `test_fast_relaunch.py` uses a 5× Gazebo physics speedup during measurement but reports wall-clock time without disclosure — the "9.01s" headline is not reproducible at 1× and doesn't represent the developer's actual wait.
2. Its timestamp filter (`msg.timestamp < int(time.time() * 1e6)`) compares PX4 sim-time (µs since Gazebo epoch ≈ 0 after reset) against Unix epoch (≈ 1.75×10¹⁵ µs), silently discarding every post-reset message. The "ground reset verified" check is a false positive.
3. It only restarts PX4, not ROS nodes — this doesn't represent the primary developer scenario (editing `src/`).

Additionally: `wait_ready.py` defines `_params_sent()` but never calls it, so "stack ready" misses the gcs_heartbeat params gate.

---

## Goal

A `just bench` command that measures the real developer cycle for a `src/` edit with warm Gazebo:

```
edit src/  →  just sim stop  →  just sim bg  →  STACK READY
```

Output is honest wall-clock milestones at 1× physics (or with pre-arm acceleration clearly disclosed). No pass/fail — purely informational for development optimization.

---

## Scenario Definition

**Scenario B — ROS node change, warm Gazebo:**
- Gazebo stays running throughout (world reset via `gz service`, not process kill)
- ROS nodes + PX4 are killed (`just sim stop`) and relaunched (`just sim bg`)
- Python-only changes require zero colcon rebuild (`--symlink-install` already in place)
- Finish line: **stack ready** = all three gates pass

**Stack ready gates:**
1. `/fmu/out/vehicle_local_position` appears in `ros2 topic list` (XRCE bridge alive)
2. TCP connect to `127.0.0.1:9090` succeeds (rosbridge open)
3. Latest sim log contains `"Params committed"` (gcs_heartbeat sent `COM_ARM_WO_GPS=1` to the new PX4 instance)

Gate 3 is the usual bottleneck; it sets the headline `t_ready`.

---

## Physics Boundary Rule

The arming event is the hard line:

| Window | Rule |
|---|---|
| Pre-arm (EKF2 convergence) | Physics acceleration is a valid optimization. If used, it must be disclosed in bench output and automatically restored to 1× at/before arm. |
| Post-arm | Gazebo `real_time_factor` must be 1×. No mass, thrust, drag, or dynamics params altered. |

**PX4 SITL convenience params are always permitted** — they gate safety checks, not flight physics:
- `COM_ARM_WO_GPS=1`
- `CBRK_SUPPLY_CHK=894281`
- `COM_SPOOLUP_TIME=0.0`
- `EKF2_GPS_CHECK=0`
- `EKF2_GPS_CTRL=7`

---

## Changes

### Phase 1 — Cleanup (on `main`)

| File | Action |
|---|---|
| `tools/test_fast_relaunch.py` | Delete |
| `tools/wait_ready.py` | Fix: wire `_params_sent()` into ready loop as third gate |
| `tools/benchmark_startup.py` | Track in git (honest cold-start baseline, correct methodology) |
| `tools/diag_flight.py` | Track in git (live flight state monitor, debugging companion) |

`sim_full.launch.py`, `tasks.py`, `gz_lifecycle.py` — no changes in this phase.

**`wait_ready.py` fix detail:** The ready loop currently exits when topic + rosbridge pass. Extend the condition:

```python
if rosbridge_ok and topic_ok and params_ok:
    typer.echo("Stack ready.")
    raise typer.Exit(0)
```

`_params_sent()` already returns `False` (not raise) when no log file exists — no crash risk on early polling.

---

### Phase 2 — `tools/bench_relaunch.py` + `just bench`

New script. No physics tricks in the default path. Optional `--fast-ekf2` flag enables pre-arm 5× acceleration with automatic 1× restore at arm event.

**Milestones measured:**

| Milestone | How detected |
|---|---|
| `t_stop` | `just sim stop` subprocess returns |
| `t_launch` | `just sim bg` spawned |
| `t_xrce` | topic appears in `ros2 topic list` |
| `t_rosbridge` | TCP connect to `:9090` succeeds |
| `t_params` | latest sim log contains `"Params committed"` |
| `t_ready` | last of t_xrce / t_rosbridge / t_params |

**Output format:**

```
=== Warm Relaunch Benchmark (1× physics) ===
  sim stop complete             +3.1s
  sim bg launched               +3.4s
  XRCE / first topic live       +14.2s  (+10.8s from launch)
  rosbridge :9090 open          +15.0s  (+11.6s from launch)
  gcs params committed          +22.7s  (+19.3s from launch)
  STACK READY                   +22.7s  (+19.3s from launch)
```

With `--fast-ekf2`:
```
=== Warm Relaunch Benchmark [pre-arm: 5× physics] ===
  sim stop complete             +3.1s
  sim bg launched               +3.4s
  XRCE / first topic live       +8.1s   (+4.7s wall / ~23s simulated)
  rosbridge :9090 open          +8.3s
  gcs params committed          +9.2s   (+5.8s wall / ~29s simulated)
  [1× restored at arm]
  STACK READY                   +9.2s
```

Arm detection for `--fast-ekf2`: the bench script subscribes to `/fmu/out/vehicle_status` (same PX4_QOS as other tools) and watches for `arming_state == ARMING_STATE_ARMED`. On that event it immediately calls the `gz service set_physics` reset to `real_time_factor: 1.0` before returning the stack-ready result.

**`just bench` in `tasks.py`:** new command, follows distrobox pattern of other sim commands.

---

### Phase 3 — Worktree Experiments

Each experiment gets its own branch and worktree. Survives only if it moves `t_ready` by ≥ 3s averaged over 3 runs. Abandoned cleanly otherwise.

**Experiment 1 — Partial restart**

Kill only ROS nodes that could have changed (`mission_manager`, `offboard_controller`, `state_estimator`, `px4_topic_relay`). Leave `MicroXRCEAgent`, `rosbridge`, `gcs_heartbeat` alive. Since gcs_heartbeat survives, no re-handshake with PX4 → `t_params` should drop significantly.

Risk: stale ROS subscriptions if nodes are killed mid-flight. If this causes instability, abandon.

Branch: `exp/partial-restart`

**Experiment 2 — Faster gcs_heartbeat reconnect**

`gcs_heartbeat.py` polls with `recv_match(timeout=1.0)` — up to ~1s overhead per poll cycle. Tightening to `0.1s` and adding explicit reconnect detection when PX4 restarts could save 1–3s from `t_params`.

Risk: low. Isolated change, easy to revert.

Branch: `exp/faster-heartbeat`

**Worktree setup pattern:**
```bash
git worktree add ../ros-px4-template-exp-<name> -b exp/<name>
# implement, run: just bench  (3 runs, average t_ready)
# if Δt_ready < 3s: git worktree remove ../ros-px4-template-exp-<name> && git branch -d exp/<name>
# if win: PR to main, remove worktree after merge
```

---

## Success Criteria

- `just bench` runs end-to-end and prints milestone table
- Numbers are at 1× physics (default) with no undisclosed speedups
- `--fast-ekf2` variant clearly discloses pre-arm acceleration and reports simulated time alongside wall-clock
- `wait_ready.py` won't return "ready" until gcs params are confirmed sent
- No untracked tool files remain

---

## Out of Scope

- SIH (Simulator-in-Hardware) as an alternative to Gazebo — separate decision
- CI integration / regression gating — separate decision after baseline is known
- Changes to scenario tests or E2E cycle
