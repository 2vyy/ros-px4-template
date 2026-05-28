# Fast Warm Relaunch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cut `edit → arm confirmed` from ~21s to ~9-11s on warm relaunch.

**Architecture:** Six targeted changes across SITL config, one additive guard in shared node code, and sim tooling. No PX4 source changes. No `hardware.yaml` or `hardware.launch.py` changes. All fast-path changes are isolated to `sim.yaml`, `sim_full.launch.py`, `sim_cleanup.py`, `tasks.py`, SITL tooling, and one additive+conservative change to `offboard_controller.py`.

**Tech Stack:** Python, ROS 2 Jazzy, PX4 SITL v1.17, Gazebo Harmonic, pymavlink, uXRCE-DDS

---

## Problem Analysis

Current warm relaunch timeline (measured baseline ~11.4s "stack ready", ~21s to arm):

```
t=0       launch
t=0.9s    ROS nodes start
t=3-4s    MicroXRCEAgent binds port 8888
t=4-5s    PX4 uxrce_dds_client connects → VehicleLocalPosition published
           → _xrce_connect_time set in offboard_controller
t=5-7s    vehicle_status.arming_state reaches STANDBY
t=10-11s  mavlink boot_complete fires → GCS port 18570 opens
           → gcs_heartbeat gets reply → "Params committed" → "stack ready"
t=19-20s  arm_delay_s (15s) expires → arm command sent  ← ACTUAL TARGET
```

**Root cause of arming delay:** `arm_delay_s: 15.0` was set conservatively to wait for
GCS params to be committed. Since we now pre-set all bypass params via `PX4_PARAM_*`
env vars in `sim_full.launch.py` (applied by PX4 rcS *before any module starts*), this
wait is no longer necessary. The params are in effect before XRCE connects.

**Root cause of GCS lag:** `mavlink boot_complete` is the last line of PX4's rcS init
script, after EKF2, vehicle setup, navigator, and logging all start. XRCE starts several
steps earlier. The GCS gate is not a useful readiness signal — `vehicle_status.arming_state`
via DDS is.

---

## Target Timeline (after all changes)

```
t=0       launch
t=0.9s    stop complete
t=1.8s    sim bg launched
t=2.0s    MicroXRCEAgent already listening (persistent)
t=3.5-4s  PX4 uxrce_dds_client connects → XRCE topics live
t=5-6s    vehicle_status.arming_state = STANDBY
t=6-7s    arm_delay_s (3s) expires + _px4_ever_standby=True → arm sent
t=7-8s    arm ACK'd, drone armed
```

---

## Scope Boundaries

**In scope (this spec):**
- `config/params/sim.yaml` — `arm_delay_s` reduction
- `src/core/.../nodes/offboard_controller.py` — additive STANDBY gate
- `tools/bench_relaunch.py`, `tools/wait_ready.py` — replace GCS log gate
- `tools/sim_cleanup.py` — graceful PX4 SIGTERM
- `sim/launch/sim_full.launch.py` — session key rotation, agent persistence check
- `tasks.py` — preemptive world reset in stop path

**Explicitly out of scope:**
- PX4 ROMFS/rcS/airframe source — not touched
- `config/params/hardware.yaml` — not touched
- `hardware/launch/hardware.launch.py` — not touched
- ROS node persistence across restarts (T2-E) — deferred, needs more experiment
- EKF2 state persistence, component containers — deferred

---

## Changes

### Change 1: Reduce `arm_delay_s` in sim.yaml

**File:** `config/params/sim.yaml`

Reduce `arm_delay_s: 15.0` to `arm_delay_s: 3.0`. This is safe because all PX4 bypass
params (`COM_ARM_WO_GPS=1`, `CBRK_SUPPLY_CHK`, `COM_SPOOLUP_TIME=0`, `EKF2_GPS_CHECK=0`)
are already applied by `PX4_PARAM_*` env vars before any PX4 module starts — before
commander, before XRCE, before everything. Nothing from the GCS side needs to be awaited.

The 3s floor provides a brief settle after XRCE connects for timestamp sync and setpoints
to stabilize. It is a lower bound; the new `_px4_ever_standby` gate (Change 2) is the
primary readiness signal.

**Expected gain:** ~12s off time-to-arm.

---

### Change 2: STANDBY gate in `offboard_controller.py`

**File:** `src/core/ros_px4_template_core/nodes/offboard_controller.py`

`_status_cb` already subscribes to `VehicleStatus`. Add a `_px4_ever_standby` flag:

```python
# In __init__:
self._px4_ever_standby: bool = False

# In _status_cb, alongside existing _armed check:
self._px4_ever_standby = (
    self._px4_ever_standby
    or msg.arming_state == VehicleStatus.ARMING_STATE_STANDBY
)
```

Add to the `xrce_ready` condition:

```python
xrce_ready = (
    self._xrce_connect_time is not None
    and (time.monotonic() - self._xrce_connect_time) >= self._arm_delay_s
    and self._setpoints_sent > 5
    and self._px4_ever_standby  # NEW
)
```

**Hardware impact:** Strictly more conservative — arming cannot fire until PX4 explicitly
reports readiness. On real hardware, PX4 takes longer to reach STANDBY (GPS lock, EKF
convergence) and `hardware.yaml` keeps its own `arm_delay_s`. No regression risk.

---

### Change 3: Replace GCS bench gate with `vehicle_status` STANDBY poll

**Files:** `tools/bench_relaunch.py`, `tools/wait_ready.py`

Replace the `_params_sent()` log-scraping function with `_px4_standby()` in both files:

```python
def _px4_standby() -> bool:
    """Return True if PX4 vehicle_status shows arming_state == STANDBY (2)."""
    try:
        result = subprocess.run(
            ["ros2", "topic", "echo", "--once", "/fmu/out/vehicle_status"],
            capture_output=True,
            text=True,
            timeout=3,
        )
        return "arming_state: 2" in result.stdout
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False
```

Replace the third gate check from `_params_sent(after_mtime)` to `_px4_standby()` in
both the polling loop and the milestone label (rename `"gcs params committed"` to
`"PX4 in STANDBY"`).

`gcs_heartbeat` continues to run as a background service for its reconnect/resend
functionality, but is no longer in the critical "stack ready" path.

**Effect on `just bench` output:** "stack ready" reports ~5-7s instead of ~11s, directly
corresponding to when arming becomes possible.

---

### Change 4: Graceful PX4 SIGTERM in `sim_cleanup.py`

**File:** `tools/sim_cleanup.py`

Before the group kill fires, send SIGTERM to the PX4 process specifically and wait up
to 1.5s for clean shutdown. PX4 writes `parameters.bson` on SIGTERM, and on the next
warm boot it loads params from disk — skipping the `SYS_AUTOCONFIG` param-reset block
in rcS.

```python
def _graceful_px4_stop(timeout_s: float = 1.5) -> None:
    """Send SIGTERM to px4 process; wait up to timeout_s before falling through."""
    import signal as _signal
    try:
        result = subprocess.run(
            ["pgrep", "-x", "px4"],
            capture_output=True, text=True, timeout=2,
        )
        for pid_str in result.stdout.splitlines():
            try:
                os.kill(int(pid_str), _signal.SIGTERM)
            except ProcessLookupError:
                pass
        time.sleep(timeout_s)
    except Exception:
        pass
```

Call `_graceful_px4_stop()` at the start of the kill sequence, before `_kill_pidfile_group()`.

**Expected gain:** ~0.5s off PX4 warm boot (params loaded from disk, reset skipped).

---

### Change 5: XRCE session key rotation + MicroXRCEAgent persistence

**Files:** `sim/launch/sim_full.launch.py`, `tools/sim_cleanup.py`

#### 5a: Session key rotation

In `sim_full.launch.py`, add `UXRCE_DDS_KEY` to `common_env` in `_gz_px4_stack`.
It must appear alongside the other `PX4_PARAM_*` exports (rcS applies all of them
unconditionally at the same point in init):

```python
import time as _time
session_key = (_time.time_ns() // 1_000_000) % 65534 + 1  # 1-65535, ms-resolution
```

Add `f"export PX4_PARAM_UXRCE_DDS_KEY={session_key}; "` to the `common_env` string
alongside the existing `PX4_PARAM_COM_ARM_WO_GPS`, `PX4_PARAM_CBRK_SUPPLY_CHK`, etc.
lines. Order within the block doesn't matter — all are applied in a single rcS loop.

Each PX4 restart gets a unique XRCE session ID. The surviving MicroXRCEAgent abandons
the old session (key mismatch) and creates a fresh one for the new PX4 instance — no
session conflict.

#### 5b: Agent persistence check

In `sim_full.launch.py`, in `generate_launch_description()` (or in the hardware launch
include), wrap MicroXRCEAgent startup in a port check:

```python
def _xrce_agent_running() -> bool:
    import socket as _socket
    try:
        with _socket.create_connection(("127.0.0.1", 8888), timeout=0.3):
            return True
    except OSError:
        return False
```

If `_xrce_agent_running()` returns True: skip launching a new agent (print a message
noting the existing agent will be reused). If False: launch as before (full backward compat).

#### 5c: Don't kill agent on `sim stop`

In `sim_cleanup.py`, exclude `MicroXRCEAgent` from kill patterns by default. Add a
`--full` flag (or `--kill-services`) that includes it when full teardown is needed.

Update `sim stop` in `tasks.py` to accept a `--full` flag: without `--full`, skip
MicroXRCEAgent (warm path default). With `--full`, kill everything including the agent.
`just sim stop` (no flag) → warm stop. `just sim stop full` → full teardown.
The `justfile` `sim-stop` recipe passes no flag; add a new recipe or overload `sim stop`
to accept `full` as an argument (consistent with how `sim bg`, `sim gui` etc. work).

**Expected gain:** ~1-2s — XRCE topics appear as soon as PX4's `uxrce_dds_client` connects
to the already-listening agent; no agent startup delay.

---

### Change 6: Preemptive world reset in stop path

**Files:** `tasks.py`, `sim/launch/sim_full.launch.py`

#### 6a: Reset world during stop

In `tasks.py`, in the sim stop sequence (after killing PX4 and ROS processes, while
Gazebo is still running), call `reset_world()` and write a flag file on success:

```python
from tools.gz_lifecycle import gazebo_matches, reset_world
_RESET_FLAG = Path("/tmp/gz_world_reset")
_WORLD_FILE = ROOT / "logs" / "gz_world.txt"  # written by sim_full cold-path launch

# In sim stop, after killing processes:
world = _WORLD_FILE.read_text().strip() if _WORLD_FILE.exists() else ""
if world and gazebo_matches(world):
    if reset_world(world):
        _RESET_FLAG.write_text(world)
```

#### 6b: Skip reset in launch if already done

In `sim_full.launch.py`, warm path in `_gz_px4_stack`:

```python
_RESET_FLAG = Path("/tmp/gz_world_reset")
already_reset = _RESET_FLAG.exists() and _RESET_FLAG.read_text().strip() == world
if already_reset:
    _RESET_FLAG.unlink(missing_ok=True)
    print(f"[sim_full] World already reset during stop — skipping", flush=True)
else:
    reset_ok = reset_world(world)
    ...
```

**Expected gain:** ~0.3s — world reset happens in parallel with PX4/ROS teardown rather
than on the critical path of the next launch.

---

## Testing

Each change has a clear verification path:

| Change | How to verify |
|---|---|
| 1 (arm_delay_s) | `just bench` — arm milestone appears ~12s sooner |
| 2 (STANDBY gate) | `just sim bg && just wait-ready` — watch for arm in logs, no premature arm |
| 3 (bench gate) | `just bench` — "PX4 in STANDBY" milestone at ~5-7s instead of ~11s |
| 4 (graceful stop) | `just sim stop && just sim bg` — check `logs/sim_*.log` for param reset absent |
| 5 (agent persist) | `just sim stop && just sim bg` — no MicroXRCEAgent startup line in log |
| 6 (world reset) | `just sim stop && just sim bg` — "World already reset" log line in launch |

End-to-end: `just bench` should report arm at ~7-8s from launch. `just test e2e` must
still pass unchanged (it runs full scenarios including arming).

---

## Measurement Baseline (before starting)

Run `just bench` three times on current main to lock in baseline:
```
current: ~11.4s stack ready, ~19-21s to arm (arm milestone not yet measured by bench)
```

After all changes, update the bench memory with new numbers.

---

## Rollout Order

Implement in this order (each change is independently testable):

1. Change 3 (bench gate update) — update measurement first so we have honest numbers
2. Change 1 (arm_delay_s) + Change 2 (STANDBY gate) — biggest win, deploy together
3. Change 4 (graceful stop) — independent
4. Change 5 (XRCE session key + persistence) — needs both parts deployed together
5. Change 6 (preemptive reset) — independent polish
