# Sim Speed Flag + Bench Removal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the bench tooling entirely and add an explicit `--speed` flag to `just sim` that sets Gazebo's physics real-time factor for headless/bg simulation runs.

**Architecture:** The `--speed` value flows from the `just sim` CLI arg → `tasks.py sim()` (validates, ignores on gui/hardware) → passed as a `speed:=N` launch argument to `sim_full.launch.py` → a new `_set_gz_physics()` helper calls `gz service set_physics` after Gazebo is confirmed running, in both the warm and cold launch paths. No new justfile recipes; the existing `sim *args` passthrough handles everything.

**Tech Stack:** Python (typer, subprocess), ROS 2 launch (OpaqueFunction, LaunchConfiguration), Gazebo Harmonic (`gz service gz.msgs.Physics`), pytest + typer.testing.CliRunner.

---

### Task 1: Remove bench tooling

**Files:**
- Delete: `tools/bench_relaunch.py`
- Delete: `tests/unit/test_bench_relaunch.py`
- Modify: `tasks.py` (remove `bench()` command, lines 702–715)
- Modify: `justfile` (remove `bench` recipe, lines 33–35)

- [ ] **Step 1: Delete the two bench files**

```bash
rm tools/bench_relaunch.py tests/unit/test_bench_relaunch.py
```

- [ ] **Step 2: Remove `bench()` from tasks.py**

Delete this block from `tasks.py` (lines 702–715):

```python
@app.command()
def bench(
    fast_ekf2: bool = typer.Option(
        False, "--fast-ekf2", help="5× pre-arm physics (disclosed in output)"
    ),
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

- [ ] **Step 3: Remove bench recipe from justfile**

Delete these 3 lines from `justfile`:

```
# Warm-relaunch benchmark: stop → relaunch → stack ready (honest 1× physics)
bench *args:
    @just _run bench {{args}}
```

- [ ] **Step 4: Verify unit tests still pass**

```bash
uv run pytest tests/unit/ -v
```

Expected: all tests pass; no reference to `bench_relaunch` or `test_bench_relaunch`.

- [ ] **Step 5: Commit**

```bash
git add -u tools/bench_relaunch.py tests/unit/test_bench_relaunch.py tasks.py justfile
git commit -m "remove: bench tooling (bench_relaunch.py, just bench, test_bench_relaunch)"
```

---

### Task 2: Add `--speed` flag with validation to `tasks.py sim`

**Files:**
- Modify: `tasks.py` (add `speed` param to `sim()`, validate it, pass to launch)
- Create: `tests/unit/test_sim_speed_validation.py`

The `speed` param must be validated before any subprocess runs. On `gui` or `hardware` modes it is ignored with a warning. On `headless` and `bg` it is passed as `speed:={speed}` to the `ros2 launch` command.

- [ ] **Step 1: Write the failing validation tests**

Create `tests/unit/test_sim_speed_validation.py`:

```python
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from typer.testing import CliRunner
from tasks import app

runner = CliRunner()


def _invoke_stop(*extra):
    """Use 'stop' mode so no subprocess is spawned — we only test arg validation."""
    with patch("tasks.subprocess.run"):
        with patch("tasks._preemptive_world_reset"):
            return runner.invoke(app, ["sim", "stop", *extra])


def test_speed_zero_rejected():
    result = _invoke_stop("--speed", "0")
    assert result.exit_code != 0
    assert "speed" in result.output.lower() or "speed" in str(result.exception).lower()


def test_speed_negative_rejected():
    result = _invoke_stop("--speed", "-1")
    assert result.exit_code != 0


def test_speed_too_high_rejected():
    result = _invoke_stop("--speed", "21")
    assert result.exit_code != 0


def test_speed_one_accepted():
    result = _invoke_stop("--speed", "1.0")
    assert result.exit_code == 0


def test_speed_four_accepted():
    result = _invoke_stop("--speed", "4")
    assert result.exit_code == 0
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/unit/test_sim_speed_validation.py -v
```

Expected: all 5 tests FAIL — `--speed` option does not exist yet.

- [ ] **Step 3: Add `speed` param and validation to `sim()` in tasks.py**

In the `sim()` function signature (around line 282), add `speed` after `build`:

```python
    speed: float = typer.Option(1.0, "--speed", help="Gazebo physics speed multiplier (headless/bg only). 1.0 = real time."),
```

At the top of `sim()`, before any mode checks, add validation (insert after the closing `"""` of the docstring, around line 298):

```python
    if speed <= 0 or speed > 20:
        console.print(f"[bold red]--speed must be between 0 (exclusive) and 20 (inclusive), got {speed}[/bold red]")
        raise typer.Exit(1) from None
    if mode in ("gui", "hardware", "inspect") and speed != 1.0:
        console.print(f"[yellow]--speed {speed} ignored for '{mode}' mode (only applies to headless/bg)[/yellow]")
        speed = 1.0
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/unit/test_sim_speed_validation.py -v
```

Expected: all 5 tests PASS.

- [ ] **Step 5: Run full unit suite to check no regressions**

```bash
uv run pytest tests/unit/ -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add tasks.py tests/unit/test_sim_speed_validation.py
git commit -m "feat: add --speed flag to sim with input validation"
```

---

### Task 3: Wire `--speed` into the launch (tasks.py → sim_full.launch.py)

**Files:**
- Modify: `tasks.py` (pass `speed:={speed}` in bg and headless launch args)
- Modify: `sim/launch/sim_full.launch.py` (declare arg, read it in `_gz_px4_stack`, add `_set_gz_physics` helper, call it in both warm and cold paths)

#### Part A — Pass speed from tasks.py to the launch

- [ ] **Step 1: Add `speed:={speed}` to the bg launch args in tasks.py**

In the `mode == "bg"` block, find the `subprocess.Popen` call that launches `sim_full.launch.py` (around line 471). The current args list ends with `f"log_dir:={LOG_DIR}"`. Add one more argument:

```python
                        f"speed:={speed}",
```

Full updated args list for the Popen call:

```python
                    [
                        "ros2",
                        "launch",
                        str(ROOT / "sim" / "launch" / "sim_full.launch.py"),
                        f"world:={world}",
                        f"model:={model}",
                        f"enable_vision:={vision}",
                        "headless:=true",
                        f"log_dir:={LOG_DIR}",
                        f"speed:={speed}",
                    ],
```

- [ ] **Step 2: Add `speed:={speed}` to the foreground launch args in tasks.py**

In the foreground `mode in ("gui", "headless", "inspect")` block, find the `cmd` list built around line 533. Add `f"speed:={speed}"` after `f"log_dir:={LOG_DIR}"`:

```python
        cmd = [
            "ros2",
            "launch",
            str(ROOT / "sim" / "launch" / "sim_full.launch.py"),
            f"world:={world_val}",
            f"model:={model}",
            f"enable_vision:={vision_val}",
            f"headless:={headless_val}",
            f"log_dir:={LOG_DIR}",
            f"speed:={speed}",
        ]
```

#### Part B — Receive and apply speed in sim_full.launch.py

- [ ] **Step 3: Add `_set_gz_physics` helper to sim_full.launch.py**

Add this function after `_xrce_agent_running()` (around line 81), before `_vision_setup`:

```python
def _set_gz_physics(world: str, speed: float) -> None:
    """Set Gazebo physics real-time factor. No-op at 1.0. Non-fatal on failure."""
    if speed == 1.0:
        return
    import subprocess as _subprocess
    update_rate = int(speed * 250)
    try:
        _subprocess.run(
            [
                "gz", "service", "-s", f"/world/{world}/set_physics",
                "--reqtype", "gz.msgs.Physics",
                "--reptype", "gz.msgs.Boolean",
                "--timeout", "3000",
                "--req",
                f"real_time_factor: {speed}, real_time_update_rate: {update_rate}, max_step_size: 0.004",
            ],
            capture_output=True,
            timeout=5,
        )
        print(f"[sim_full] Physics speed set to {speed}×", flush=True)
    except Exception:
        print(f"[sim_full] WARNING: failed to set physics speed={speed}; running at default", flush=True)
```

- [ ] **Step 4: Declare `speed` launch arg in `generate_launch_description`**

In `generate_launch_description()`, find the `DeclareLaunchArgument` list (around line 264). Add the speed argument:

```python
            DeclareLaunchArgument("speed", default_value="1.0"),
```

The full list after the change:

```python
            DeclareLaunchArgument("world", default_value="default"),
            DeclareLaunchArgument("model", default_value="x500"),
            DeclareLaunchArgument("log_dir", default_value=str(project_root / "logs")),
            DeclareLaunchArgument("enable_vision", default_value="false"),
            DeclareLaunchArgument("headless", default_value="false"),
            DeclareLaunchArgument("speed", default_value="1.0"),
```

- [ ] **Step 5: Read `speed` in `_gz_px4_stack` and call `_set_gz_physics` in both paths**

In `_gz_px4_stack` (line 140), add the speed read after the existing `headless` read:

```python
    speed = float(LaunchConfiguration("speed").perform(context))
```

Then, in the **warm path** (inside `if gazebo_matches(world):`), add the call after the reset/skip block and before building `cmd`, around line 211:

```python
        _set_gz_physics(world, speed)
        cmd = common_env + px4_warm_launch
```

In the **cold path** (inside the `else:` branch), add the `gz service` call to the bash script, right after `echo "{world}" > "{world_file}"; ` (around line 226). Replace:

```python
            f'echo "{world}" > "{world_file}"; '
            f"{headless_export}" + px4_launch + "; "
```

with:

```python
            f'echo "{world}" > "{world_file}"; '
            f'gz service -s /world/{world}/set_physics --reqtype gz.msgs.Physics --reptype gz.msgs.Boolean --timeout 3000 --req "real_time_factor: {speed}, real_time_update_rate: {int(speed * 250)}, max_step_size: 0.004" 2>/dev/null || true; '
            f"{headless_export}" + px4_launch + "; "
```

- [ ] **Step 6: Run unit tests**

```bash
uv run pytest tests/unit/ -v
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add tasks.py sim/launch/sim_full.launch.py
git commit -m "feat: wire --speed through launch to gz set_physics (warm + cold paths)"
```

---

### Task 4: Smoke-test the full feature

These are live checks, not automated tests. Run inside the distrobox container.

- [ ] **Step 1: Verify `--speed` validation from CLI**

```bash
just sim stop --speed 0
```
Expected: error message mentioning `--speed`, exit 1.

```bash
just sim stop --speed 25
```
Expected: error message mentioning `--speed`, exit 1.

- [ ] **Step 2: Verify `--speed` warning is shown for gui mode**

```bash
just sim --speed 3  # then Ctrl+C immediately
```
Expected: yellow warning line `--speed 3 ignored for 'gui' mode` printed before Gazebo starts.

- [ ] **Step 3: Verify speed=1 bg still works (no regression)**

```bash
just sim bg --no-build
just sim stop
```
Expected: sim starts and stops cleanly; no physics-related errors in log.

- [ ] **Step 4: Verify `--speed 4` sets physics on bg launch**

```bash
just sim bg --speed 4 --no-build
```
Check the sim log:
```bash
grep "Physics speed set to" logs/sim_*.log | tail -1
```
Expected: `[sim_full] Physics speed set to 4.0×`

```bash
just sim stop
```

- [ ] **Step 5: Run a scenario against a speed-4 sim**

```bash
just sim bg --speed 4 --no-build
# wait for stack ready
just test scenario 01_arm_takeoff
just sim stop
```
Expected: scenario passes. Scenario timing will be faster in wall-clock time; the pass/fail result must be identical to a 1× run.

- [ ] **Step 6: Final commit if any fixups were needed**

```bash
git add -u
git commit -m "fix: speed flag smoke-test fixups" # only if needed
```
