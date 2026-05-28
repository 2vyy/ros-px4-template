# Fast Warm Relaunch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cut `edit → arm confirmed` from ~21s to ~9-11s on warm relaunch with zero PX4 source changes and zero hardware path changes.

**Architecture:** Five task groups in rollout order: (1) update bench measurement gate first so gains are visible; (2) reduce `arm_delay_s` + add STANDBY DDS guard in offboard_controller — the biggest single win; (3) graceful PX4 SIGTERM for faster warm boot; (4) XRCE session-key rotation + MicroXRCEAgent persistence to eliminate agent startup overhead; (5) preemptive world reset during stop to remove reset from the launch critical path.

**Tech Stack:** Python 3.12, ROS 2 Jazzy (inside distrobox `ubuntu`), PX4 SITL v1.17, Gazebo Harmonic, pymavlink, uXRCE-DDS. Unit tests run on host with `uv run pytest`. ROS integration verified inside distrobox.

---

## File Map

| File | Change |
|---|---|
| `tools/bench_relaunch.py` | Replace `_params_sent` + `LOG_DIR` with `_px4_standby`; update gate label |
| `tools/wait_ready.py` | Same — replace `_params_sent` with `_px4_standby`; update docstring + label |
| `tests/unit/test_bench_relaunch.py` | Replace `_params_sent` tests with `_px4_standby` tests |
| `tests/unit/test_wait_ready.py` | Replace `_params_sent` patches with `_px4_standby` patches |
| `config/params/sim.yaml` | `arm_delay_s: 15.0 → 3.0` |
| `src/core/ros_px4_template_core/nodes/offboard_controller.py` | Add `_px4_ever_standby` flag; add to `xrce_ready` |
| `tools/sim_cleanup.py` | Add `_graceful_px4_stop()`; move `MicroXRCEAgent` out of `_PATTERNS` into `_FULL_PATTERNS` only |
| `tests/unit/test_sim_cleanup.py` | Add test: MicroXRCEAgent NOT in `_PATTERNS`, IS in `_FULL_PATTERNS` |
| `sim/launch/sim_full.launch.py` | Add `_xrce_agent_running()` check; conditional agent launch; session key in `common_env` |
| `tasks.py` | Call `reset_world()` + write flag in sim stop handler |

---

## Task 1: Replace bench gate — `_params_sent` → `_px4_standby`

**Files:**
- Modify: `tools/bench_relaunch.py`
- Modify: `tools/wait_ready.py`
- Modify: `tests/unit/test_bench_relaunch.py`
- Modify: `tests/unit/test_wait_ready.py`

Background: `bench_relaunch.py` and `wait_ready.py` currently gate "stack ready" on a log-scrape for `"Params committed"` from gcs_heartbeat. This appears at ~10-11s. We replace it with a live poll of `vehicle_status.arming_state == 2` (STANDBY) via `ros2 topic echo`. This shows at ~5-7s — aligning the metric with when arming actually becomes possible.

- [ ] **Step 1: Write failing tests for `_px4_standby` in `test_bench_relaunch.py`**

Open `tests/unit/test_bench_relaunch.py`. Remove the four existing `_params_sent` tests (everything from `# ── _params_sent ──` to end of file) and add these in their place:

```python
# ── _px4_standby ─────────────────────────────────────────────────────────────

def test_px4_standby_true_when_arming_state_2():
    from bench_relaunch import _px4_standby
    mock_result = MagicMock()
    mock_result.stdout = "---\narming_state: 2\nnav_state: 0\n"
    with patch("bench_relaunch.subprocess.run", return_value=mock_result):
        assert _px4_standby() is True


def test_px4_standby_false_when_arming_state_not_2():
    from bench_relaunch import _px4_standby
    mock_result = MagicMock()
    mock_result.stdout = "---\narming_state: 0\nnav_state: 0\n"
    with patch("bench_relaunch.subprocess.run", return_value=mock_result):
        assert _px4_standby() is False


def test_px4_standby_false_on_timeout():
    from bench_relaunch import _px4_standby
    with patch("bench_relaunch.subprocess.run", side_effect=subprocess.TimeoutExpired("ros2", 3)):
        assert _px4_standby() is False


def test_px4_standby_false_on_missing_ros2():
    from bench_relaunch import _px4_standby
    with patch("bench_relaunch.subprocess.run", side_effect=FileNotFoundError):
        assert _px4_standby() is False
```

Also add `from unittest.mock import MagicMock, patch` and `import subprocess` near the top imports.

- [ ] **Step 2: Run tests — expect failures**

```bash
uv run pytest tests/unit/test_bench_relaunch.py -v
```

Expected: `ImportError` or `AttributeError: module 'bench_relaunch' has no attribute '_px4_standby'`

- [ ] **Step 3: Implement changes in `bench_relaunch.py`**

Remove these lines:
```python
import os          # line 13 — no longer needed after LOG_DIR removal
```
```python
LOG_DIR = ROOT / "logs"          # remove
_PARAMS_MARKER = "Params committed"  # remove
```

Remove the entire `_params_sent` function (lines 50-61 currently).

Add `_px4_standby` after `_topic_live`:

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

In `main()`, remove `launch_mtime_cutoff = time.time()` (no longer needed).

Replace the params gate in the polling loop:
```python
# OLD:
if not params_ok and _params_sent(launch_mtime_cutoff):
    t_params = time.monotonic()
    params_ok = True
    print(_format_milestone("gcs params committed", t_params, t0, t_launch), flush=True)

# NEW:
if not params_ok and _px4_standby():
    t_params = time.monotonic()
    params_ok = True
    print(_format_milestone("PX4 in STANDBY", t_params, t0, t_launch), flush=True)
```

Also update the timeout message at the bottom:
```python
# OLD:
f"topic={topic_ok} rosbridge={rosbridge_ok} params={params_ok}",
# NEW: (no change needed — variable names stay the same)
```

- [ ] **Step 4: Run tests — expect pass**

```bash
uv run pytest tests/unit/test_bench_relaunch.py -v
```

Expected: 6 PASSED (2 `_format_milestone` tests + 4 new `_px4_standby` tests)

- [ ] **Step 5: Write failing tests for `_px4_standby` in `test_wait_ready.py`**

Open `tests/unit/test_wait_ready.py`. Replace the entire file with:

```python
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

from typer.testing import CliRunner

from wait_ready import app


def test_ready_requires_standby_gate():
    """Stack ready must wait for all three gates including PX4 STANDBY."""
    runner = CliRunner()
    with (
        patch("wait_ready._topic_live", return_value=True),
        patch("wait_ready._port_open", return_value=True),
        patch("wait_ready._px4_standby", return_value=True),
    ):
        result = runner.invoke(app, ["--timeout", "5"])
    assert result.exit_code == 0
    assert "PX4 in STANDBY" in result.output
    assert "Stack ready" in result.output


def test_ready_blocks_until_standby():
    """Stack ready must not exit while STANDBY gate is pending."""
    runner = CliRunner()
    call_count = 0

    def fake_standby() -> bool:
        nonlocal call_count
        call_count += 1
        return call_count >= 3  # fails first two polls

    with (
        patch("wait_ready._topic_live", return_value=True),
        patch("wait_ready._port_open", return_value=True),
        patch("wait_ready._px4_standby", fake_standby),
    ):
        result = runner.invoke(app, ["--timeout", "5"])

    assert result.exit_code == 0
    assert 2 <= call_count < 20


def test_timeout_reports_standby_state():
    """On timeout, output must include standby status."""
    runner = CliRunner()
    with (
        patch("wait_ready._topic_live", return_value=True),
        patch("wait_ready._port_open", return_value=True),
        patch("wait_ready._px4_standby", return_value=False),
    ):
        result = runner.invoke(app, ["--timeout", "1"])
    assert result.exit_code == 1
    assert "params=False" in result.output
```

- [ ] **Step 6: Run — expect failures**

```bash
uv run pytest tests/unit/test_wait_ready.py -v
```

Expected: failures patching `wait_ready._px4_standby` (function doesn't exist yet)

- [ ] **Step 7: Implement changes in `wait_ready.py`**

Update the module docstring (top of file) — change line 8 from:
```
  3. gcs_heartbeat has received a PX4 heartbeat and sent COM_ARM_WO_GPS=1,
     confirmed by checking the gcs_heartbeat log for "Params committed".
```
to:
```
  3. PX4 vehicle_status.arming_state == STANDBY (2), confirming commander
     is up and PX4 is ready to accept an arm command.
```

Remove `_LOG_DIR`:
```python
_LOG_DIR = Path(__file__).resolve().parent.parent / "logs"  # remove this line
```

Remove the entire `_params_sent` function (lines 53-62 currently).

Add `_px4_standby` after `_topic_live`:

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

In `main()`, rename `params_ok` variable and replace gate + messages:

```python
# replace:
params_ok = _params_sent()
if params_ok:
    typer.echo("  [OK] gcs params committed")
# with:
params_ok = _px4_standby()
if params_ok:
    typer.echo("  [OK] PX4 in STANDBY")
```

The timeout message uses f-string `params={'OK' if params_ok else '...'}` — no change needed, variable name is the same.

- [ ] **Step 8: Run — expect pass**

```bash
uv run pytest tests/unit/test_wait_ready.py tests/unit/test_bench_relaunch.py -v
```

Expected: all PASSED

- [ ] **Step 9: Lint**

```bash
uv run ruff check tools/bench_relaunch.py tools/wait_ready.py && uv run ruff format --check tools/bench_relaunch.py tools/wait_ready.py
```

Fix any issues with `uv run ruff format tools/bench_relaunch.py tools/wait_ready.py`.

- [ ] **Step 10: Commit**

```bash
git add tools/bench_relaunch.py tools/wait_ready.py tests/unit/test_bench_relaunch.py tests/unit/test_wait_ready.py
git commit -m "feat: replace GCS log gate with vehicle_status STANDBY poll

bench_relaunch and wait_ready now gate 'stack ready' on PX4
reporting arming_state == STANDBY via DDS, replacing the log-scrape
for 'Params committed'. Stack ready now reports ~5-7s instead of
~11s, aligning with when arming actually becomes possible."
```

---

## Task 2: arm_delay_s reduction + STANDBY gate in offboard_controller

**Files:**
- Modify: `config/params/sim.yaml`
- Modify: `src/core/ros_px4_template_core/nodes/offboard_controller.py`

Background: `arm_delay_s: 15.0` is the single biggest arming delay. It was set conservatively to wait for GCS params. Those params are now pre-set via `PX4_PARAM_*` env vars before any PX4 module starts. We reduce to 3.0s and add a `_px4_ever_standby` latch so arm only fires after PX4 explicitly confirms readiness. The controller already subscribes to `VehicleStatus` in `_status_cb` — this change adds two lines there and one to `xrce_ready`.

Note: `offboard_controller.py` imports `rclpy` at module level and cannot be imported in host-side unit tests. Verification is done via live sim run — check `logs/offboard_controller.jsonl` for `ARM_COMMAND_SENT` appearing sooner.

- [ ] **Step 1: Reduce `arm_delay_s` in `config/params/sim.yaml`**

```yaml
# config/params/sim.yaml  (full file after change)
offboard_controller:
  ros__parameters:
    auto_arm: true
    arm_delay_s: 3.0
    offboard_prestream_s: 3.0
    target_altitude_m: 3.0

mission_manager:
  ros__parameters:
    # Use the inspect_aruco waypoint mission for sim. Set to "" for hover-only mode.
    mission_file: "config/missions/inspect_aruco.yaml"
    tick_rate_hz: 10.0
    takeoff_altitude_m: 3.0
```

- [ ] **Step 2: Add `_px4_ever_standby` init in `offboard_controller.py`**

In `__init__`, after `self._arm_fail_reason = ""` (currently line 87), add:

```python
self._px4_ever_standby: bool = False
```

- [ ] **Step 3: Latch `_px4_ever_standby` in `_status_cb`**

`_status_cb` is currently (lines 141-143):

```python
def _status_cb(self, msg: VehicleStatus) -> None:
    self._armed = msg.arming_state == VehicleStatus.ARMING_STATE_ARMED
    self._nav_state = int(msg.nav_state)
```

Change it to:

```python
def _status_cb(self, msg: VehicleStatus) -> None:
    self._armed = msg.arming_state == VehicleStatus.ARMING_STATE_ARMED
    self._nav_state = int(msg.nav_state)
    self._px4_ever_standby = (
        self._px4_ever_standby
        or msg.arming_state == VehicleStatus.ARMING_STATE_STANDBY
    )
```

- [ ] **Step 4: Add `_px4_ever_standby` to `xrce_ready` in `_update_state_machine`**

`xrce_ready` is currently (lines 183-187):

```python
xrce_ready = (
    self._xrce_connect_time is not None
    and (time.monotonic() - self._xrce_connect_time) >= self._arm_delay_s
    and self._setpoints_sent > 5
)
```

Change it to:

```python
xrce_ready = (
    self._xrce_connect_time is not None
    and (time.monotonic() - self._xrce_connect_time) >= self._arm_delay_s
    and self._setpoints_sent > 5
    and self._px4_ever_standby
)
```

- [ ] **Step 5: Lint**

```bash
uv run ruff check src/core/ros_px4_template_core/nodes/offboard_controller.py && uv run ruff format --check src/core/ros_px4_template_core/nodes/offboard_controller.py
```

- [ ] **Step 6: Run all unit tests to confirm no regressions**

```bash
uv run pytest tests/unit/ -v
```

Expected: all pass (offboard_controller changes are not unit-tested on host; all other tests unchanged)

- [ ] **Step 7: Commit**

```bash
git add config/params/sim.yaml src/core/ros_px4_template_core/nodes/offboard_controller.py
git commit -m "feat: reduce arm_delay_s to 3s and add STANDBY gate

arm_delay_s: 15.0 -> 3.0 in sim.yaml only (hardware.yaml untouched).
Add _px4_ever_standby latch in offboard_controller: arm command cannot
fire until vehicle_status.arming_state == STANDBY is observed at least
once, replacing the implicit 15s timer as the primary readiness gate."
```

---

## Task 3: Graceful PX4 SIGTERM in sim_cleanup.py

**Files:**
- Modify: `tools/sim_cleanup.py`
- Modify: `tests/unit/test_sim_cleanup.py`

Background: PX4 currently receives SIGKILL (no chance to flush). PX4 writes `parameters.bson` on clean SIGTERM shutdown. On warm relaunch, if `parameters.bson` already contains the correct params, PX4 skips the `SYS_AUTOCONFIG` param-reset block in rcS (~0.5s saved). We send SIGTERM first, wait 1.5s, then fall through to the normal SIGKILL path.

- [ ] **Step 1: Write failing test in `test_sim_cleanup.py`**

Add to `tests/unit/test_sim_cleanup.py`:

```python
import os
import signal
from unittest.mock import MagicMock, call, patch


def test_graceful_px4_stop_sends_sigterm():
    """_graceful_px4_stop must SIGTERM the PX4 pid found by pgrep."""
    mock_run = MagicMock()
    mock_run.return_value = MagicMock(stdout="1234\n5678\n")
    with (
        patch("sim_cleanup.subprocess.run", mock_run),
        patch("sim_cleanup.os.kill") as mock_kill,
        patch("sim_cleanup.time.sleep"),
    ):
        from sim_cleanup import _graceful_px4_stop
        _graceful_px4_stop()
    assert call(1234, signal.SIGTERM) in mock_kill.call_args_list
    assert call(5678, signal.SIGTERM) in mock_kill.call_args_list


def test_graceful_px4_stop_silent_on_no_px4():
    """_graceful_px4_stop must not raise if pgrep finds nothing."""
    mock_run = MagicMock()
    mock_run.return_value = MagicMock(stdout="")
    with (
        patch("sim_cleanup.subprocess.run", mock_run),
        patch("sim_cleanup.os.kill") as mock_kill,
        patch("sim_cleanup.time.sleep"),
    ):
        from sim_cleanup import _graceful_px4_stop
        _graceful_px4_stop()
    mock_kill.assert_not_called()


def test_graceful_px4_stop_silent_on_exception():
    """_graceful_px4_stop must not propagate exceptions."""
    with patch("sim_cleanup.subprocess.run", side_effect=Exception("fail")):
        from sim_cleanup import _graceful_px4_stop
        _graceful_px4_stop()  # must not raise
```

- [ ] **Step 2: Run — expect failures**

```bash
uv run pytest tests/unit/test_sim_cleanup.py -v
```

Expected: `AttributeError: module 'sim_cleanup' has no attribute '_graceful_px4_stop'`

- [ ] **Step 3: Implement `_graceful_px4_stop` in `sim_cleanup.py`**

Add after the `_stop_ros2_daemon` function (before `def main()`):

```python
def _graceful_px4_stop(timeout_s: float = 1.5) -> None:
    """SIGTERM px4 process and wait briefly so it can flush parameters.bson."""
    try:
        result = subprocess.run(
            ["pgrep", "-x", "px4"],
            capture_output=True,
            text=True,
            timeout=2,
        )
        for pid_str in result.stdout.splitlines():
            pid_str = pid_str.strip()
            if pid_str.isdigit():
                try:
                    os.kill(int(pid_str), signal.SIGTERM)
                except ProcessLookupError:
                    pass
        time.sleep(timeout_s)
    except Exception:
        pass
```

- [ ] **Step 4: Call `_graceful_px4_stop()` from `main()` before the kill passes**

In `main()`, add one line before the `with ThreadPoolExecutor` block (currently starting around line 141):

```python
def main() -> None:
    ap = argparse.ArgumentParser(description="Stop sim processes.")
    ap.add_argument(
        "--full",
        action="store_true",
        help="Also kill Gazebo (full teardown). Default keeps Gazebo warm.",
    )
    args = ap.parse_args()

    patterns = _FULL_PATTERNS if args.full else _PATTERNS

    if args.full:
        try:
            sys.path.insert(0, str(Path(__file__).parent))
            from gz_lifecycle import clear_world_record
            clear_world_record()
        except Exception:
            pass

    _graceful_px4_stop()  # ← ADD THIS LINE

    # --- Pass 1: kill pidfile group + all known patterns in parallel ---
    with ThreadPoolExecutor(max_workers=3) as ex:
        ...
```

- [ ] **Step 5: Run tests — expect pass**

```bash
uv run pytest tests/unit/test_sim_cleanup.py -v
```

Expected: all 6 tests PASSED (3 original + 3 new)

- [ ] **Step 6: Lint**

```bash
uv run ruff check tools/sim_cleanup.py && uv run ruff format --check tools/sim_cleanup.py
```

- [ ] **Step 7: Commit**

```bash
git add tools/sim_cleanup.py tests/unit/test_sim_cleanup.py
git commit -m "feat: graceful PX4 SIGTERM before SIGKILL in sim_cleanup

SIGTERM px4 process and wait 1.5s before the normal SIGKILL pass.
PX4 flushes parameters.bson on clean shutdown; the next warm boot
loads params from disk and skips the SYS_AUTOCONFIG reset block (~0.5s)."
```

---

## Task 4: XRCE session key rotation + MicroXRCEAgent persistence

**Files:**
- Modify: `tools/sim_cleanup.py`
- Modify: `tests/unit/test_sim_cleanup.py`
- Modify: `sim/launch/sim_full.launch.py`

Background: Currently `sim stop` kills MicroXRCEAgent (it's in `_PATTERNS`). On relaunch, the agent takes ~1-2s to start and bind port 8888. We want to keep it alive across warm stops. Problem: if the agent is alive from the previous run, PX4's `uxrce_dds_client` tries to resume the old XRCE session (same `UXRCE_DDS_KEY=1`), causing session conflicts. Fix: generate a unique session key per PX4 launch via `PX4_PARAM_UXRCE_DDS_KEY`. The old session is abandoned, a new one is created instantly.

Two changes together: move agent out of `_PATTERNS`; add session key + conditional agent launch in `sim_full.launch.py`.

- [ ] **Step 1: Write failing test for MicroXRCEAgent exclusion in `test_sim_cleanup.py`**

Add to `tests/unit/test_sim_cleanup.py`:

```python
def test_xrce_agent_excluded_from_default_patterns():
    """MicroXRCEAgent must NOT be killed on normal sim stop (kept alive for reuse)."""
    assert r"MicroXRCEAgent" not in sim_cleanup._PATTERNS, (
        "MicroXRCEAgent must not be in _PATTERNS — it is kept alive across warm stops"
    )


def test_xrce_agent_included_in_full_patterns():
    """MicroXRCEAgent must be killed on --full teardown."""
    assert r"MicroXRCEAgent" in sim_cleanup._FULL_PATTERNS, (
        "MicroXRCEAgent must be in _FULL_PATTERNS — killed only on full teardown"
    )
```

- [ ] **Step 2: Run — expect one failure**

```bash
uv run pytest tests/unit/test_sim_cleanup.py::test_xrce_agent_excluded_from_default_patterns -v
```

Expected: FAILED — `MicroXRCEAgent` is currently in `_PATTERNS`

- [ ] **Step 3: Move `MicroXRCEAgent` from `_PATTERNS` to `_FULL_PATTERNS` in `sim_cleanup.py`**

`_PATTERNS` (lines 31-47 currently): remove `r"MicroXRCEAgent",` from the list.

`_FULL_PATTERNS` (line 50 currently) is defined as:
```python
_FULL_PATTERNS = [*_PATTERNS, r"gz sim", r"gz server", r"gzserver"]
```

Change it to:
```python
_FULL_PATTERNS = [*_PATTERNS, r"MicroXRCEAgent", r"gz sim", r"gz server", r"gzserver"]
```

- [ ] **Step 4: Run sim_cleanup tests — all pass**

```bash
uv run pytest tests/unit/test_sim_cleanup.py -v
```

Expected: all 8 tests PASSED

- [ ] **Step 5: Add `_xrce_agent_running()` helper to `sim_full.launch.py`**

Add this function near the top of `sim_full.launch.py`, after the existing `_gz_paths` helpers and before `_vision_setup`:

```python
def _xrce_agent_running() -> bool:
    """Return True if MicroXRCEAgent is already listening on UDP 8888."""
    import socket as _socket
    try:
        # MicroXRCEAgent listens on UDP, not TCP — use a brief UDP probe instead.
        # A non-refused response (including ICMP port-unreachable) means nothing is there.
        # The simplest reliable check: try to connect a UDP socket and send a byte.
        # If the port is bound, no OS error is raised immediately on connect (UDP is
        # connectionless). Use pgrep instead as the authoritative check.
        result = subprocess.run(
            ["pgrep", "-x", "MicroXRCEAgent"],
            capture_output=True,
            text=True,
            timeout=1,
        )
        return bool(result.stdout.strip())
    except Exception:
        return False
```

Note: MicroXRCEAgent binds a UDP port, not TCP — `socket.create_connection` (TCP) won't work. `pgrep` on the process name is the reliable check.

- [ ] **Step 6: Add session key rotation to `common_env` in `_gz_px4_stack`**

In `_gz_px4_stack`, `common_env` starts at line 138. Add `UXRCE_DDS_KEY` alongside the other `PX4_PARAM_*` exports:

```python
import time as _time
_session_key = (_time.time_ns() // 1_000_000) % 65534 + 1  # 1-65535, ms-resolution

common_env = (
    "set -e; "
    "export GZ_IP=127.0.0.1; "
    "export PX4_PARAM_COM_ARM_WO_GPS=1; "
    "export PX4_PARAM_CBRK_SUPPLY_CHK=894281; "
    "export PX4_PARAM_COM_SPOOLUP_TIME=0.0; "
    "export PX4_PARAM_EKF2_GPS_CHECK=0; "
    "export PX4_PARAM_EKF2_GPS_CTRL=7; "
    f"export PX4_PARAM_UXRCE_DDS_KEY={_session_key}; "   # ← ADD THIS LINE
    f'export GZ_SIM_RESOURCE_PATH="{gz_paths}"; '
    ...  # rest unchanged
)
```

- [ ] **Step 7: Wrap MicroXRCEAgent launch in `generate_launch_description` with persistence check**

In `generate_launch_description()`, the `ExecuteProcess` for MicroXRCEAgent is:

```python
ExecuteProcess(
    cmd=["MicroXRCEAgent", "udp4", "-p", "8888"],
    name="micro_xrce_agent",
    output="screen",
),
```

Replace it with a conditional:

```python
*(
    []
    if _xrce_agent_running()
    else [
        ExecuteProcess(
            cmd=["MicroXRCEAgent", "udp4", "-p", "8888"],
            name="micro_xrce_agent",
            output="screen",
        )
    ]
),
```

Also add a print statement before the `return LaunchDescription(...)` so it's visible in launch output. The full updated `generate_launch_description` body:

```python
def generate_launch_description() -> LaunchDescription:
    project_root = Path(__file__).resolve().parents[2]
    px4_dir = _require_px4_dir()
    gz_paths = _gz_paths(project_root, px4_dir)

    agent_alive = _xrce_agent_running()
    if agent_alive:
        print("[sim_full] MicroXRCEAgent already running — reusing existing agent", flush=True)
    else:
        print("[sim_full] MicroXRCEAgent not running — starting fresh agent", flush=True)

    hardware_launch = PythonLaunchDescriptionSource(
        str(project_root / "hardware" / "launch" / "hardware.launch.py")
    )

    agent_action = [] if agent_alive else [
        ExecuteProcess(
            cmd=["MicroXRCEAgent", "udp4", "-p", "8888"],
            name="micro_xrce_agent",
            output="screen",
        )
    ]

    return LaunchDescription(
        [
            DeclareLaunchArgument("world", default_value="default"),
            DeclareLaunchArgument("model", default_value="x500"),
            DeclareLaunchArgument("log_dir", default_value=str(project_root / "logs")),
            DeclareLaunchArgument("enable_vision", default_value="false"),
            DeclareLaunchArgument("headless", default_value="false"),
            SetEnvironmentVariable(name="GZ_IP", value="127.0.0.1"),
            SetEnvironmentVariable(name="GZ_SIM_RESOURCE_PATH", value=gz_paths),
            *agent_action,
            OpaqueFunction(function=_gz_px4_stack),
            ExecuteProcess(
                cmd=["python3", str(project_root / "tools" / "gcs_heartbeat.py")],
                name="gcs_heartbeat",
                output="screen",
            ),
            OpaqueFunction(function=_clock_bridge),
            OpaqueFunction(function=_vision_setup),
            IncludeLaunchDescription(
                hardware_launch,
                launch_arguments={
                    "use_sim_time": "true",
                    "config": "sim",
                    "log_dir": LaunchConfiguration("log_dir"),
                }.items(),
            ),
        ]
    )
```

- [ ] **Step 8: Lint**

```bash
uv run ruff check tools/sim_cleanup.py sim/launch/sim_full.launch.py
uv run ruff format --check tools/sim_cleanup.py sim/launch/sim_full.launch.py
```

Apply `uv run ruff format` to any files that need reformatting.

- [ ] **Step 9: Run all unit tests**

```bash
uv run pytest tests/unit/ -v
```

Expected: all pass

- [ ] **Step 10: Commit**

```bash
git add tools/sim_cleanup.py tests/unit/test_sim_cleanup.py sim/launch/sim_full.launch.py
git commit -m "feat: XRCE agent persistence + session key rotation on warm stop

Move MicroXRCEAgent out of _PATTERNS so sim stop keeps it alive.
Generate a unique UXRCE_DDS_KEY per PX4 launch to avoid session
conflicts with the persisting agent. sim_full.launch.py skips
starting a new agent if one is already running (pgrep check)."
```

---

## Task 5: Preemptive world reset during sim stop

**Files:**
- Modify: `tasks.py`
- Modify: `sim/launch/sim_full.launch.py`

Background: Currently `reset_world()` runs at the start of `_gz_px4_stack` (during launch). Moving it to `sim stop` means the reset happens in parallel with PX4/ROS teardown — by the time the next `sim bg` launches, Gazebo is already clean. A flag file `/tmp/gz_world_reset` carries the world name from stop to launch. If the flag exists and matches the requested world, the launch skips the reset.

- [ ] **Step 1: Add world reset call to sim stop in `tasks.py`**

Find the sim stop handler in `tasks.py` (currently around line 280-283):

```python
if mode == "stop":
    console.print("[cyan]Stopping sim (Gazebo stays warm for next launch)...[/cyan]")
    subprocess.run(["uv", "run", "python", "tools/sim_cleanup.py"], cwd=str(ROOT))
    return
```

Replace with:

```python
if mode == "stop":
    console.print("[cyan]Stopping sim (Gazebo stays warm for next launch)...[/cyan]")
    subprocess.run(["uv", "run", "python", "tools/sim_cleanup.py"], cwd=str(ROOT))
    # Preemptively reset world while Gazebo is still running, so launch can skip it.
    _preemptive_world_reset(world)
    return
```

Add this helper function before the `sim` command (near the other helpers at the top of `tasks.py`):

```python
_GZ_RESET_FLAG = Path("/tmp/gz_world_reset")

def _preemptive_world_reset(world: str) -> None:
    """Reset Gazebo world now (during stop) so the next launch can skip it."""
    try:
        sys.path.insert(0, str(ROOT / "tools"))
        from gz_lifecycle import gazebo_matches, reset_world  # type: ignore[import]
        if gazebo_matches(world):
            if reset_world(world):
                _GZ_RESET_FLAG.write_text(world)
                console.print(f"[green]World '{world}' reset preemptively.[/green]")
    except Exception:
        pass  # non-fatal — launch will reset on its own if flag absent
```

Note: `sys` is already imported in tasks.py.

- [ ] **Step 2: Add skip logic to `_gz_px4_stack` in `sim_full.launch.py`**

In `_gz_px4_stack`, the warm-path block currently starts at line 162:

```python
if gazebo_matches(world):
    print(f"[sim_full] Gazebo warm for world='{world}' — resetting world state", flush=True)
    reset_ok = reset_world(world)
    if not reset_ok:
        print(
            "[sim_full] WARNING: world reset failed; PX4 connecting to unreset state",
            flush=True,
        )
    ...
```

Replace with:

```python
if gazebo_matches(world):
    _RESET_FLAG = Path("/tmp/gz_world_reset")
    already_reset = (
        _RESET_FLAG.exists() and _RESET_FLAG.read_text().strip() == world
    )
    if already_reset:
        _RESET_FLAG.unlink(missing_ok=True)
        print(
            f"[sim_full] World '{world}' already reset during stop — skipping",
            flush=True,
        )
    else:
        print(
            f"[sim_full] Gazebo warm for world='{world}' — resetting world state",
            flush=True,
        )
        reset_ok = reset_world(world)
        if not reset_ok:
            print(
                "[sim_full] WARNING: world reset failed; PX4 connecting to unreset state",
                flush=True,
            )
    ...  # px4_warm_launch and cmd = common_env + px4_warm_launch unchanged
```

- [ ] **Step 3: Lint**

```bash
uv run ruff check tasks.py sim/launch/sim_full.launch.py
uv run ruff format --check tasks.py sim/launch/sim_full.launch.py
```

- [ ] **Step 4: Run all unit tests**

```bash
uv run pytest tests/unit/ -v
```

Expected: all pass (no unit tests for tasks.py or launch files)

- [ ] **Step 5: Commit**

```bash
git add tasks.py sim/launch/sim_full.launch.py
git commit -m "feat: preemptive world reset during sim stop

Call reset_world() at the end of sim stop (while Gazebo is still
warm) and write /tmp/gz_world_reset. sim_full.launch.py checks the
flag on warm launch and skips the reset if already done, removing
it from the launch critical path (~0.3s saved)."
```

---

## Verification Checklist

After all tasks are committed, verify end-to-end in distrobox:

```bash
distrobox enter ubuntu -- bash -lc "cd ~/Projects/ros-px4-template && just sim kill"
# (wait for full teardown)
distrobox enter ubuntu -- bash -lc "cd ~/Projects/ros-px4-template && just bench"
```

Expected `just bench` output shape:
```
=== Warm Relaunch Benchmark [1× physics throughout] ===

Stopping sim (Gazebo stays warm)...
  sim stop complete                      +0.9s
  sim bg launched                        +1.8s
  XRCE / first topic live                +4.2s  (+2.4s from launch)
  rosbridge :9090 open                   +4.5s  (+2.7s from launch)
  PX4 in STANDBY                         +6.1s  (+4.3s from launch)

  STACK READY                            +6.1s  (+4.3s from launch)
```

Arm confirmed (check `logs/offboard_controller.jsonl`):
```bash
grep ARM_COMMAND_SENT logs/offboard_controller.jsonl | tail -1
grep ARM_ACK_OK logs/offboard_controller.jsonl | tail -1
```
Arm command should appear at ~7-8s from launch start, confirmed at ~8-9s.

Run E2E to confirm no regressions:
```bash
distrobox enter ubuntu -- bash -lc "cd ~/Projects/ros-px4-template && just test e2e"
```

Expected: passes unchanged.
