# Honest Warm-Relaunch Benchmark Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the broken/cheating fast-relaunch test with an honest `just bench` tool that measures the real developer cycle (edit `src/` → warm Gazebo restart → stack ready) at 1× physics.

**Architecture:** Phase 1 cleans up broken files and wires the missing params gate in `wait_ready.py`. Phase 2 builds `tools/bench_relaunch.py` — a milestone-printing script with no hidden speedups — and exposes it as `just bench`. Phase 3 runs two isolated worktree experiments targeting the main bottleneck (`t_params`), each with a ≥3s go/no-go bar.

**Tech Stack:** Python 3.12, typer, rclpy (PX4_QOS), asyncio, pytest, unittest.mock, just, uv, distrobox ubuntu

---

## Phase 1 — Cleanup

### Task 1: Delete test_fast_relaunch.py and track untracked tools

**Files:**
- Delete: `tools/test_fast_relaunch.py`
- Track: `tools/benchmark_startup.py`, `tools/diag_flight.py`

- [ ] **Step 1: Delete the broken test file**

```bash
rm tools/test_fast_relaunch.py
```

- [ ] **Step 2: Stage deletions and new files**

```bash
git rm tools/test_fast_relaunch.py
git add tools/benchmark_startup.py tools/diag_flight.py
```

- [ ] **Step 3: Verify staging**

```bash
git status
```

Expected: `deleted: tools/test_fast_relaunch.py`, `new file: tools/benchmark_startup.py`, `new file: tools/diag_flight.py`

- [ ] **Step 4: Commit**

```bash
git commit -m "$(cat <<'EOF'
chore: remove broken fast-relaunch test, track tool scripts

test_fast_relaunch.py used undisclosed 5x physics and a broken
timestamp filter (Unix epoch vs PX4 sim-time). benchmark_startup.py
and diag_flight.py are honest tools worth keeping.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: Fix wait_ready.py — wire in the params gate

**Files:**
- Modify: `tools/wait_ready.py:65–99`
- Create: `tests/unit/test_wait_ready.py`

- [ ] **Step 1: Write failing tests**

Create `tests/unit/test_wait_ready.py`:

```python
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

from typer.testing import CliRunner

from wait_ready import app


def test_ready_requires_params_gate():
    """Stack ready must wait for all three gates including params."""
    runner = CliRunner()
    with (
        patch("wait_ready._topic_live", return_value=True),
        patch("wait_ready._port_open", return_value=True),
        patch("wait_ready._params_sent", return_value=True),
    ):
        result = runner.invoke(app, ["--timeout", "5"])
    assert result.exit_code == 0
    assert "gcs params committed" in result.output
    assert "Stack ready" in result.output


def test_ready_blocks_until_params():
    """Stack ready must not exit while params gate is pending."""
    runner = CliRunner()
    call_count = 0

    def fake_params() -> bool:
        nonlocal call_count
        call_count += 1
        return call_count >= 3  # fails first two polls

    with (
        patch("wait_ready._topic_live", return_value=True),
        patch("wait_ready._port_open", return_value=True),
        patch("wait_ready._params_sent", fake_params),
    ):
        result = runner.invoke(app, ["--timeout", "5"])

    assert result.exit_code == 0
    assert call_count >= 3


def test_timeout_reports_params_state():
    """On timeout, output must include params status."""
    runner = CliRunner()
    with (
        patch("wait_ready._topic_live", return_value=True),
        patch("wait_ready._port_open", return_value=True),
        patch("wait_ready._params_sent", return_value=False),
    ):
        result = runner.invoke(app, ["--timeout", "1"])
    assert result.exit_code == 1
    assert "params=" in result.output or "params=" in (result.stderr or "")
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
uv run pytest tests/unit/test_wait_ready.py -v
```

Expected: `FAILED` on all three — `gcs params committed` not in output, exit on two gates.

- [ ] **Step 3: Implement the fix in wait_ready.py**

Replace lines 65–99 (`main` function body):

```python
@app.command()
def main(timeout: int = typer.Option(180, "--timeout", help="Seconds before giving up")) -> None:
    deadline = time.monotonic() + timeout
    typer.echo(f"Waiting for sim stack (timeout {timeout}s)...")

    rosbridge_ok = False
    topic_ok = False
    params_ok = False

    while time.monotonic() < deadline:
        if not topic_ok:
            topic_ok = _topic_live(_REQUIRED_TOPIC)
            if topic_ok:
                typer.echo(f"  [OK] {_REQUIRED_TOPIC} live")

        if not rosbridge_ok:
            rosbridge_ok = _port_open(_ROSBRIDGE_PORT)
            if rosbridge_ok:
                typer.echo("  [OK] rosbridge :9090 open")

        if not params_ok:
            params_ok = _params_sent()
            if params_ok:
                typer.echo("  [OK] gcs params committed")

        if rosbridge_ok and topic_ok and params_ok:
            typer.echo("Stack ready.")
            raise typer.Exit(0)

        remaining = int(deadline - time.monotonic())
        typer.echo(
            f"  waiting... topic={'OK' if topic_ok else '...'} "
            f"rosbridge={'OK' if rosbridge_ok else '...'} "
            f"params={'OK' if params_ok else '...'} ({remaining}s left)"
        )
        time.sleep(_POLL_INTERVAL_S)

    typer.echo(
        f"TIMEOUT after {timeout}s — topic={topic_ok} rosbridge={rosbridge_ok} params={params_ok}",
        err=True,
    )
    sys.exit(1)
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
uv run pytest tests/unit/test_wait_ready.py -v
```

Expected: all three `PASSED`.

- [ ] **Step 5: Run full unit suite to check for regressions**

```bash
uv run pytest tests/unit/ -v
```

Expected: all existing tests still pass.

- [ ] **Step 6: Commit**

```bash
git add tools/wait_ready.py tests/unit/test_wait_ready.py
git commit -m "$(cat <<'EOF'
fix: wire gcs params gate into wait_ready stack-ready check

_params_sent() was defined but never called. Stack could report
"ready" before COM_ARM_WO_GPS=1 reached the new PX4 instance,
causing a silent arming race.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Phase 2 — bench_relaunch.py + just bench

### Task 3: Create bench_relaunch.py — pure helper functions

**Files:**
- Create: `tools/bench_relaunch.py`
- Create: `tests/unit/test_bench_relaunch.py`

- [ ] **Step 1: Write failing unit tests**

Create `tests/unit/test_bench_relaunch.py`:

```python
from __future__ import annotations

import sys
import time
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))


# ── _format_milestone ────────────────────────────────────────────────────────

def test_format_milestone_no_launch_ref():
    from bench_relaunch import _format_milestone
    t0 = 1000.0
    line = _format_milestone("sim stop complete", 1003.1, t0)
    assert "+3.1s" in line
    assert "sim stop complete" in line
    assert "from launch" not in line


def test_format_milestone_with_launch_ref():
    from bench_relaunch import _format_milestone
    t0 = 1000.0
    t_launch = 1003.4
    line = _format_milestone("XRCE / first topic live", 1014.2, t0, t_launch)
    assert "+14.2s" in line
    assert "+10.8s from launch" in line


# ── _params_sent ─────────────────────────────────────────────────────────────

def test_params_sent_no_logs(tmp_path):
    from bench_relaunch import _params_sent
    with patch("bench_relaunch.LOG_DIR", tmp_path):
        assert _params_sent(after_mtime=0.0) is False


def test_params_sent_stale_log(tmp_path):
    from bench_relaunch import _params_sent
    log = tmp_path / "sim_20260101T000000.log"
    log.write_text("Params committed\n")
    # Set mtime to 1000 seconds ago
    import os
    old_time = time.time() - 1000
    os.utime(log, (old_time, old_time))
    with patch("bench_relaunch.LOG_DIR", tmp_path):
        # after_mtime is now → log is stale
        assert _params_sent(after_mtime=time.time()) is False


def test_params_sent_fresh_log_with_marker(tmp_path):
    from bench_relaunch import _params_sent
    log = tmp_path / "sim_20260101T000000.log"
    log.write_text("some output\nParams committed\nmore output\n")
    with patch("bench_relaunch.LOG_DIR", tmp_path):
        # after_mtime is in the past → log is fresh
        assert _params_sent(after_mtime=0.0) is True


def test_params_sent_fresh_log_without_marker(tmp_path):
    from bench_relaunch import _params_sent
    log = tmp_path / "sim_20260101T000000.log"
    log.write_text("some output\nno params here\n")
    with patch("bench_relaunch.LOG_DIR", tmp_path):
        assert _params_sent(after_mtime=0.0) is False
```

- [ ] **Step 2: Run tests — verify they fail (ImportError expected)**

```bash
uv run pytest tests/unit/test_bench_relaunch.py -v
```

Expected: `ImportError: No module named 'bench_relaunch'`

- [ ] **Step 3: Create tools/bench_relaunch.py with helper functions**

Create `tools/bench_relaunch.py`:

```python
#!/usr/bin/env python3
"""Honest warm-relaunch benchmark: stop → relaunch → stack ready at 1× physics.

Usage:
    uv run python tools/bench_relaunch.py            # 1× physics throughout
    uv run python tools/bench_relaunch.py --fast-ekf2  # 5× pre-arm, disclosed
"""

from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = ROOT / "logs"

_ROSBRIDGE_PORT = 9090
_REQUIRED_TOPIC = "/fmu/out/vehicle_local_position"
_PARAMS_MARKER = "Params committed"


def _port_open(port: int) -> bool:
    """Return True if a TCP listener is accepting connections on port."""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1.0):
            return True
    except OSError:
        return False


def _topic_live(topic: str) -> bool:
    """Return True if topic appears in ros2 topic list."""
    try:
        result = subprocess.run(
            ["ros2", "topic", "list"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return topic in result.stdout.splitlines()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def _params_sent(after_mtime: float) -> bool:
    """Return True if a sim log newer than after_mtime contains 'Params committed'."""
    sim_logs = sorted(LOG_DIR.glob("sim_*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not sim_logs:
        return False
    newest = sim_logs[0]
    if newest.stat().st_mtime < after_mtime:
        return False
    try:
        return _PARAMS_MARKER in newest.read_text(errors="replace")
    except OSError:
        return False


def _set_gz_physics(rtf: float) -> None:
    """Set Gazebo physics real-time factor. Silently ignores errors (gz may not be running)."""
    update_rate = int(rtf * 250)
    try:
        subprocess.run(
            [
                "gz", "service", "-s", "/world/default/set_physics",
                "--reqtype", "gz.msgs.Physics",
                "--reptype", "gz.msgs.Boolean",
                "--timeout", "3000",
                "--req", f"real_time_factor: {rtf}, real_time_update_rate: {update_rate}, max_step_size: 0.004",
            ],
            capture_output=True,
            timeout=5,
        )
    except Exception:
        pass


def _format_milestone(label: str, t_abs: float, t0: float, t_launch: float | None = None) -> str:
    """Format a single benchmark milestone line."""
    elapsed = t_abs - t0
    if t_launch is not None:
        from_launch = t_abs - t_launch
        return f"  {label:<38} +{elapsed:.1f}s  (+{from_launch:.1f}s from launch)"
    return f"  {label:<38} +{elapsed:.1f}s"
```

- [ ] **Step 4: Run unit tests — verify they pass**

```bash
uv run pytest tests/unit/test_bench_relaunch.py -v
```

Expected: all 6 tests `PASSED`.

- [ ] **Step 5: Commit helpers**

```bash
git add tools/bench_relaunch.py tests/unit/test_bench_relaunch.py
git commit -m "$(cat <<'EOF'
feat: add bench_relaunch helper functions with unit tests

Pure helper layer: _params_sent, _format_milestone, _port_open,
_topic_live, _set_gz_physics. Main measurement loop follows in
next commit.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: Add bench_relaunch.py main measurement loop

**Files:**
- Modify: `tools/bench_relaunch.py` (append `main()`)

- [ ] **Step 1: Append main() to tools/bench_relaunch.py**

Add the following at the bottom of `tools/bench_relaunch.py` (after `_format_milestone`):

```python


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Honest warm-relaunch benchmark (Scenario B: edit src/, warm Gazebo)."
    )
    ap.add_argument(
        "--fast-ekf2",
        action="store_true",
        help="Use 5× Gazebo physics pre-arm for faster EKF2 convergence. "
             "Disclosed in output. 1× restored at stack-ready.",
    )
    args = ap.parse_args()

    mode_label = "pre-arm: 5× physics" if args.fast_ekf2 else "1× physics throughout"
    print(f"\n=== Warm Relaunch Benchmark [{mode_label}] ===\n", flush=True)
    print("Scenario B: edit src/ → sim stop → sim bg (warm Gazebo) → stack ready\n", flush=True)

    t0 = time.monotonic()

    # ── Step 1: Stop sim (kills ROS nodes + PX4, Gazebo stays warm) ──────────
    print("Stopping sim (Gazebo stays warm)...", flush=True)
    result = subprocess.run(
        ["uv", "run", "python", "tools/sim_cleanup.py"],
        cwd=str(ROOT),
    )
    if result.returncode != 0:
        print("WARNING: sim_cleanup.py returned non-zero (may not have been running)", flush=True)
    t_stop = time.monotonic()
    print(_format_milestone("sim stop complete", t_stop, t0), flush=True)

    # ── Step 2: Optionally set 5× pre-arm physics ─────────────────────────────
    if args.fast_ekf2:
        _set_gz_physics(5.0)
        print("  [5× pre-arm physics set on Gazebo]", flush=True)

    # ── Step 3: Record log freshness cutoff, then launch ─────────────────────
    launch_mtime_cutoff = time.time()

    subprocess.Popen(
        ["uv", "run", "python", "tasks.py", "sim", "bg"],
        cwd=str(ROOT),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    t_launch = time.monotonic()
    print(_format_milestone("sim bg launched", t_launch, t0), flush=True)

    # ── Step 4: Poll all three gates ─────────────────────────────────────────
    topic_ok = rosbridge_ok = params_ok = False
    t_xrce = t_rosbridge = t_params = None
    deadline = t_launch + 180.0

    while time.monotonic() < deadline:
        if not topic_ok and _topic_live(_REQUIRED_TOPIC):
            t_xrce = time.monotonic()
            topic_ok = True
            print(_format_milestone("XRCE / first topic live", t_xrce, t0, t_launch), flush=True)

        if not rosbridge_ok and _port_open(_ROSBRIDGE_PORT):
            t_rosbridge = time.monotonic()
            rosbridge_ok = True
            print(_format_milestone("rosbridge :9090 open", t_rosbridge, t0, t_launch), flush=True)

        if not params_ok and _params_sent(launch_mtime_cutoff):
            t_params = time.monotonic()
            params_ok = True
            print(_format_milestone("gcs params committed", t_params, t0, t_launch), flush=True)

        if topic_ok and rosbridge_ok and params_ok:
            t_ready = max(t_xrce, t_rosbridge, t_params)  # type: ignore[type-var]

            if args.fast_ekf2:
                _set_gz_physics(1.0)
                print("  [1× physics restored at stack-ready]", flush=True)

            print(flush=True)
            print(
                _format_milestone("STACK READY", t_ready, t0, t_launch),
                flush=True,
            )
            print(flush=True)
            return

        time.sleep(0.2)

    print(
        f"\nTIMEOUT after 180s — "
        f"topic={topic_ok} rosbridge={rosbridge_ok} params={params_ok}",
        file=sys.stderr,
    )
    sys.exit(1)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Verify existing unit tests still pass (main() has no unit tests — subprocess-bound)**

```bash
uv run pytest tests/unit/test_bench_relaunch.py -v
```

Expected: all 6 tests still `PASSED` (main() not imported by tests).

- [ ] **Step 3: Commit**

```bash
git add tools/bench_relaunch.py
git commit -m "$(cat <<'EOF'
feat: add bench_relaunch main measurement loop

Measures stop→launch→XRCE/rosbridge/params at 1× physics.
Optional --fast-ekf2 flag uses 5× pre-arm with disclosure and
automatic 1× restore at stack-ready.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: Wire up just bench in tasks.py and justfile

**Files:**
- Modify: `tasks.py` (add `bench` command after existing commands)
- Modify: `justfile` (add `bench` recipe)

- [ ] **Step 1: Add bench command to tasks.py**

In `tasks.py`, add the following after the `test` command (find it by searching for `@app.command()` near `def test(`):

```python
@app.command()
def bench(
    fast_ekf2: bool = typer.Option(False, "--fast-ekf2", help="5× pre-arm physics (disclosed in output)"),
):
    """Honest warm-relaunch benchmark: stop → relaunch → stack ready (1× physics, no cheating)."""
    cmd = ["uv", "run", "python", "tools/bench_relaunch.py"]
    if fast_ekf2:
        cmd.append("--fast-ekf2")
    try:
        subprocess.run(cmd, check=True, cwd=str(ROOT))
    except subprocess.CalledProcessError:
        raise typer.Exit(1) from None
```

- [ ] **Step 2: Add bench recipe to justfile**

In `justfile`, add after the `log` recipe:

```just
# Warm-relaunch benchmark: stop → relaunch → stack ready (honest 1× physics)
bench *args:
    @just _run bench {{args}}
```

- [ ] **Step 3: Verify just lists bench**

```bash
just --list
```

Expected: `bench` appears in the recipe list.

- [ ] **Step 4: Run full unit suite**

```bash
uv run pytest tests/unit/ -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add tasks.py justfile
git commit -m "$(cat <<'EOF'
feat: add just bench command for warm-relaunch timing

Exposes bench_relaunch.py as a first-class just recipe.
--fast-ekf2 flag passes through for optional pre-arm acceleration.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: Record honest baseline numbers

**Files:** none — observational step

- [ ] **Step 1: Ensure sim is not already running**

```bash
just sim stop
```

- [ ] **Step 2: Start a fresh sim (cold), wait for it to stabilize**

Run inside distrobox:
```bash
distrobox enter ubuntu -- bash -lc "cd ~/Projects/ros-px4-template && just sim bg"
```

Then wait for `just wait_ready` or observe `just log tail` until the drone is hovering.

- [ ] **Step 3: Run the benchmark**

```bash
distrobox enter ubuntu -- bash -lc "cd ~/Projects/ros-px4-template && just bench"
```

- [ ] **Step 4: Record numbers**

Note the `STACK READY` time. This is the honest baseline. Typical expected range: **25–45s** from launch (dominated by EKF2 convergence + gcs_heartbeat handshake).

If `STACK READY` is < 15s, recheck that `_params_sent` is actually waiting for the new log (not a stale one).

- [ ] **Step 5: Optionally run with --fast-ekf2 to see pre-arm speedup**

```bash
distrobox enter ubuntu -- bash -lc "cd ~/Projects/ros-px4-template && just bench --fast-ekf2"
```

Note both the wall-clock `STACK READY` and that it clearly discloses `[5× pre-arm physics]`.

---

## Phase 3 — Worktree Experiments

> Each experiment targets `t_params` (the dominant bottleneck — gcs_heartbeat handshake with new PX4).
> Go/no-go: ≥ 3s improvement in mean `t_ready` over 3 runs vs. baseline.
> On failure: `git worktree remove` the tree and `git branch -d` the branch.

---

### Task 7: Experiment 1 — Persistent GCS keepalive

**Hypothesis:** If `gcs_heartbeat` stays connected across a PX4 restart, it detects the new PX4 heartbeat within seconds of PX4 boot — eliminating the current ~120s-max / ~8–10s-typical connection latency.

**Worktree:**
- Branch: `exp/partial-restart`
- Path: `../ros-px4-template-exp-partial`

**Files (in worktree):**
- Create: `tools/gcs_keepalive.py`
- Modify: `tools/bench_relaunch.py` (start keepalive before stop, pass env flag to sim bg)
- Modify: `sim/launch/sim_full.launch.py` or `hardware/launch/hardware.launch.py` (honour `SKIP_GCS_HEARTBEAT` env)

- [ ] **Step 1: Create the worktree**

```bash
git worktree add ../ros-px4-template-exp-partial -b exp/partial-restart
cd ../ros-px4-template-exp-partial
```

- [ ] **Step 2: Create tools/gcs_keepalive.py**

This is a modified `gcs_heartbeat.py` that loops forever, reconnecting whenever the PX4 connection drops:

```python
#!/usr/bin/env python3
"""Persistent GCS keepalive — reconnects across PX4 restarts and re-sends params.

Intended to run as a background process during bench cycles.
Unlike gcs_heartbeat.py (which exits after sending params once), this script
maintains a continuous reconnect loop so params are sent to each new PX4 instance
within ~0.5s of it booting.
"""

from __future__ import annotations

import time

from pymavlink import mavutil

_PARAMS: tuple[tuple[str, float, str], ...] = (
    ("COM_ARM_WO_GPS", 1.0, "INT32"),
    ("CBRK_SUPPLY_CHK", 894281.0, "INT32"),
    ("COM_SPOOLUP_TIME", 0.0, "REAL32"),
    ("EKF2_GPS_CHECK", 0.0, "INT32"),
)

_HEARTBEAT_INTERVAL_S = 0.1
_RECONNECT_INTERVAL_S = 0.5


def _send_params(conn: mavutil.mavudp) -> None:
    for name, value, ptype in _PARAMS:
        conn.mav.param_set_send(
            conn.target_system,
            conn.target_component,
            name.encode(),
            value,
            getattr(mavutil.mavlink, f"MAV_PARAM_TYPE_{ptype}"),
        )
    print("[gcs_keepalive] Params committed", flush=True)


def main() -> None:
    print("[gcs_keepalive] Starting persistent GCS keepalive on UDP 18570...", flush=True)

    while True:
        try:
            conn = mavutil.mavlink_connection("udpout:127.0.0.1:18570")
            print("[gcs_keepalive] Connecting...", flush=True)

            # Send heartbeats until PX4 replies
            deadline = time.monotonic() + 300.0  # wait up to 5 min for next PX4 boot
            got_heartbeat = False
            while time.monotonic() < deadline:
                conn.mav.heartbeat_send(
                    mavutil.mavlink.MAV_TYPE_GCS,
                    mavutil.mavlink.MAV_AUTOPILOT_INVALID,
                    0, 0, 0,
                )
                msg = conn.recv_match(type="HEARTBEAT", blocking=True, timeout=_HEARTBEAT_INTERVAL_S)
                if msg is not None:
                    conn.target_system = msg.get_srcSystem()
                    conn.target_component = msg.get_srcComponent()
                    got_heartbeat = True
                    break

            if not got_heartbeat:
                print("[gcs_keepalive] No heartbeat in 5 min — retrying", flush=True)
                continue

            print(f"[gcs_keepalive] PX4 connected (sys={conn.target_system})", flush=True)
            _send_params(conn)

            # Keep alive — detect disconnect by watching for heartbeat gaps
            last_hb = time.monotonic()
            while True:
                conn.mav.heartbeat_send(
                    mavutil.mavlink.MAV_TYPE_GCS,
                    mavutil.mavlink.MAV_AUTOPILOT_INVALID,
                    0, 0, 0,
                )
                msg = conn.recv_match(type="HEARTBEAT", blocking=True, timeout=_HEARTBEAT_INTERVAL_S)
                if msg is not None:
                    last_hb = time.monotonic()
                elif time.monotonic() - last_hb > 3.0:
                    print("[gcs_keepalive] PX4 heartbeat lost — reconnecting", flush=True)
                    break

        except Exception as exc:
            print(f"[gcs_keepalive] Error: {exc} — retrying in {_RECONNECT_INTERVAL_S}s", flush=True)
            time.sleep(_RECONNECT_INTERVAL_S)


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Modify hardware.launch.py to honour SKIP_GCS_HEARTBEAT**

In `hardware/launch/hardware.launch.py`, wrap the `gcs_heartbeat` `ExecuteProcess` in a condition:

```python
import os
# ... existing imports ...

# In generate_launch_description(), replace the gcs_heartbeat ExecuteProcess with:
*([
    ExecuteProcess(
        cmd=["python3", str(project_root / "tools" / "gcs_heartbeat.py")],
        name="gcs_heartbeat",
        output="screen",
    )
] if not os.environ.get("SKIP_GCS_HEARTBEAT") else []),
```

- [ ] **Step 4: Modify bench_relaunch.py main() to use keepalive in this experiment**

In the worktree's `tools/bench_relaunch.py`, add a `--keepalive` flag to `main()`:

```python
ap.add_argument(
    "--keepalive",
    action="store_true",
    help="Start gcs_keepalive as a background process (Experiment 1).",
)
```

Before the stop step, when `--keepalive` is set, spawn `gcs_keepalive.py` and set `SKIP_GCS_HEARTBEAT=1` in the environment passed to `tasks.py sim bg`:

```python
keepalive_proc = None
if args.keepalive:
    import os
    keepalive_proc = subprocess.Popen(
        ["uv", "run", "python", "tools/gcs_keepalive.py"],
        cwd=str(ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    print("  [gcs_keepalive started as background process]", flush=True)
```

And when spawning `tasks.py sim bg`, pass `SKIP_GCS_HEARTBEAT=1`:

```python
env = dict(os.environ) if args.keepalive else None
if args.keepalive and env:
    env["SKIP_GCS_HEARTBEAT"] = "1"

subprocess.Popen(
    ["uv", "run", "python", "tasks.py", "sim", "bg"],
    cwd=str(ROOT),
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
    env=env,
)
```

After measurement completes, kill the keepalive process if it was started.

- [ ] **Step 5: Run baseline (3 runs) in this worktree**

```bash
distrobox enter ubuntu -- bash -lc "cd ~/Projects/ros-px4-template-exp-partial && just bench"
```

Run 3 times, record each `STACK READY` time. Average = baseline_B.

- [ ] **Step 6: Run experiment (3 runs)**

```bash
distrobox enter ubuntu -- bash -lc "cd ~/Projects/ros-px4-template-exp-partial && just bench --keepalive"
```

Run 3 times, record each `STACK READY` time. Average = result_B.

- [ ] **Step 7: Go / no-go decision**

If `baseline_B - result_B >= 3.0s`: proceed to Task 9 to merge.

If `baseline_B - result_B < 3.0s`:
```bash
cd ~/Projects/ros-px4-template
git worktree remove ../ros-px4-template-exp-partial
git branch -d exp/partial-restart
```
Note the result and move on.

---

### Task 8: Experiment 2 — Faster gcs_heartbeat poll

**Hypothesis:** `gcs_heartbeat.py` calls `recv_match(timeout=1.0)` — up to ~1s of poll overhead per iteration. PX4 typically boots in ~8–10s. Tightening to `0.1s` cuts the detection lag from up to ~10s to ~0.1s.

**Worktree:**
- Branch: `exp/faster-heartbeat`
- Path: `../ros-px4-template-exp-heartbeat`

**Files (in worktree):**
- Modify: `tools/gcs_heartbeat.py:49` (one line change)

- [ ] **Step 1: Create the worktree**

```bash
git worktree add ../ros-px4-template-exp-heartbeat -b exp/faster-heartbeat
cd ../ros-px4-template-exp-heartbeat
```

- [ ] **Step 2: Change recv_match timeout**

In `tools/gcs_heartbeat.py`, line 49, change:

```python
# Before:
msg = conn.recv_match(type="HEARTBEAT", blocking=True, timeout=1.0)

# After:
msg = conn.recv_match(type="HEARTBEAT", blocking=True, timeout=0.1)
```

- [ ] **Step 3: Run baseline (3 runs)**

```bash
distrobox enter ubuntu -- bash -lc "cd ~/Projects/ros-px4-template && just bench"
```

Record 3× `STACK READY` times. Average = baseline_C.

- [ ] **Step 4: Run experiment (3 runs)**

```bash
distrobox enter ubuntu -- bash -lc "cd ~/Projects/ros-px4-template-exp-heartbeat && just bench"
```

Record 3× `STACK READY` times. Average = result_C.

- [ ] **Step 5: Go / no-go decision**

If `baseline_C - result_C >= 3.0s`: proceed to Task 9 to merge.

If `baseline_C - result_C < 3.0s`:
```bash
cd ~/Projects/ros-px4-template
git worktree remove ../ros-px4-template-exp-heartbeat
git branch -d exp/faster-heartbeat
```

---

### Task 9: Merge winning experiments (if any)

- [ ] **Step 1: For each winning experiment branch, create a PR or merge to main**

```bash
cd ~/Projects/ros-px4-template
git merge exp/<winning-branch> --no-ff -m "feat: <experiment name> — saves Xs on warm relaunch"
```

- [ ] **Step 2: Remove worktrees for merged experiments**

```bash
git worktree remove ../ros-px4-template-exp-<name>
```

- [ ] **Step 3: Run full check to confirm no regressions**

```bash
just check
```

Expected: all lints, typechecks, and unit tests pass.

- [ ] **Step 4: Run bench one final time to confirm the improved number**

```bash
distrobox enter ubuntu -- bash -lc "cd ~/Projects/ros-px4-template && just bench"
```

Record the final honest `STACK READY` time as the post-optimization baseline.

---

## Success Criteria

- `just bench` prints milestone table with honest wall-clock numbers
- Default mode is 1× physics throughout — no undisclosed speedups
- `--fast-ekf2` variant discloses pre-arm acceleration and restores 1× at stack-ready
- `just wait_ready` (via `wait_ready.py`) does not return until gcs params are confirmed
- No untracked files in `tools/`
- All unit tests pass (`just check`)
