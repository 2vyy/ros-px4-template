# Plan 009: Record a ROS 2 MCAP bag during `just sim`, stopped gracefully at teardown

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**:
> `git diff --stat 3b904a5..HEAD -- tasks.py tools/sim_cleanup.py tests/unit/test_sim_cleanup.py`
> If any of those files changed since this plan was written, compare the
> "Current state" excerpts below against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MED (touches the sim launch/teardown lifecycle; recording must never break `just sim`)
- **Depends on**: none
- **Category**: direction (integration enablement)
- **Planned at**: commit `3b904a5`, 2026-06-22

## Why this matters

This template launches a full PX4 SITL + Gazebo + ROS 2 stack with `just sim`,
but **records nothing a post-hoc analyzer can ingest** — the only artifact today
is the logfmt event log (`logs/latest.log`). A sibling project, **skein**
(`/home/ivy/Projects/skein`), reconciles a ROS 2 MCAP bag and a PX4 ULog onto one
timeline and overlays/queries them, but it has no input until this template
starts producing recordings. This is follow-up **#1** of the integration design
at `/home/ivy/Projects/skein/docs/template-integration-design.md` (§3a, §3c).

This plan makes `just sim` record a per-run MCAP bag of the flight telemetry and
stop it **cleanly with SIGINT** at teardown (a hard SIGKILL can truncate/corrupt
an open MCAP). After this lands, every `just sim` run leaves a
`logs/runs/<run-id>/bag/` MCAP that skein's `overlay --bag` can read directly.
ULog retrieval and the `just analyze` wiring are **separate, later plans** (010,
011) — explicitly out of scope here.

## Current state

Files involved:

- `tasks.py` — the typer task runner. Relevant pieces:
  - `LOG_DIR = ROOT / "logs"` and `from datetime import datetime` already imported (`tasks.py:30`, `:23`).
  - `_ros2_launch_capture_argv(...)` builds a `bash -lc` that sources ROS + the
    workspace, then runs a command — the **pattern to mirror** for sourcing ROS
    in a detached child (`tasks.py:129-150`).
  - `_ros_launch_env(...)` builds the env for launch children (`tasks.py:95-126`).
  - `_spawn_stack(...)` spawns a detached, `setsid` launch and the caller writes
    its pid to `logs/sim.pid` — the **pattern to mirror** for a detached recorder
    with its own pidfile (`tasks.py:188-201`).
  - `_teardown()` is the single funnel for all teardown (stop, failed launch,
    e2e boundary). **This is where the recorder must be stopped, before the kill
    sweep** (`tasks.py:177-185`):
    ```python
    def _teardown() -> bool:
        result = sim_cleanup.teardown()
        print(format_stopped(result["killed"], result["survivors"]))
        return not result["survivors"]
    ```
  - `sim(...)` boots the stack, writes `logs/sim.pid`, waits for readiness via
    `tools/wait_ready.py`, then prints a READY verdict (`tasks.py:450-536`). The
    readiness gate and verdict print are:
    ```python
    proc = _spawn_stack(launch_args, env, append=False)
    (LOG_DIR / "sim.pid").write_text(str(proc.pid))

    res = subprocess.run(
        ["uv", "run", "python", "tools/wait_ready.py", "--timeout", str(timeout),
         "--speed", str(speed)],
        cwd=str(ROOT),
    )
    elapsed = _time.monotonic() - started
    if res.returncode != 0:
        print(
            format_not_ready("stack did not reach readiness (topics/rosbridge/GCS params)", elapsed),
            file=sys.stderr,
        )
        _teardown()
        raise typer.Exit(int(ExitCode.FAIL))

    print(
        format_ready(
            ["/fmu topics up", "rosbridge:9090", "GCS params committed"], elapsed
        )
    )
    ```
  - `clean()` already wipes everything under `logs/` except `.gitkeep`, including
    subdirectories (`shutil.rmtree` on dirs) — so `logs/runs/` needs **no** new
    cleanup code (`tasks.py:360-376`).

- `tools/sim_cleanup.py` — the **safety-critical** exhaustive teardown. It
  SIGKILLs only a precise allow-list of stack process basenames/patterns
  (`_EXACT_BASENAMES`, `_CMDLINE_PATTERNS`, `tools/sim_cleanup.py:33-61`). Note:
  `ros2 bag` / `rosbag2` is **deliberately not** in that allow-list, and **you
  must not add it** — the file's header comment explains a false positive there
  is catastrophic inside distrobox. The recorder is instead managed by its own
  pidfile + process group (see Step 2), so `sim_cleanup` never needs to know
  about it.

- `docs/TOPICS.md` — the topic manifest (`docs/TOPICS.md:13-26`). The bag records
  a fixed subset of these (see Step 1's `_BAG_TOPICS`). Validated against the live
  graph by `just log topics`.

- `tests/unit/test_sim_cleanup.py` — the **structural pattern for the new unit
  test**: pure functions, fake process tables / injected listers, and
  `monkeypatch.setattr` on module-level helpers (`tests/unit/test_sim_cleanup.py:13-87`).

Conventions to match:

- Tools live in `tools/`, are importable, and keep side-effecting primitives in
  small module-level functions so tests can monkeypatch them (see how
  `sim_cleanup.py` wraps `_sigkill`, `_kill_pidfile_group`, `scan_survivors`).
- `tools/` is added to `sys.path` in `tasks.py:154`, then sub-modules are imported
  by bare name (e.g. `import sim_cleanup`). Add `import bag_recorder` the same way.
- Python ≥ 3.12, `from __future__ import annotations`, type hints throughout.
- Detached children use `preexec_fn=os.setsid` and a pidfile under `logs/`
  (mirror `sim.pid`).

## Commands you will need

| Purpose            | Command                                                        | Expected on success                |
|--------------------|----------------------------------------------------------------|------------------------------------|
| Full quality gate  | `just check`                                                   | exits 0; "all checks passed."      |
| Unit tests only    | `uv run pytest tests/unit/ -q --tb=short`                      | all pass                           |
| New test only      | `uv run pytest tests/unit/test_bag_recorder.py -q`             | all pass                           |
| Lint a file        | `uv run ruff check tools/bag_recorder.py tasks.py`             | exit 0                             |
| Typecheck          | `uv run ty check tools/ --exclude tools/gcs_heartbeat.py`      | exit 0                             |

`just check` runs ruff (format + fix), branch invariants, `ty`, colcon build, and
`pytest tests/unit/` (`tasks.py:379-446`). In a worktree without ROS/colcon, run
the unit-test and ruff/ty commands directly instead (see STOP conditions about
the live sim verification).

## Scope

**In scope** (the only files you should modify or create):

- `tools/bag_recorder.py` (create) — the recorder lifecycle.
- `tasks.py` (modify) — import `bag_recorder`; start the recorder in `sim()` after
  readiness; stop it first in `_teardown()`.
- `tests/unit/test_bag_recorder.py` (create) — unit tests.
- `plans/README.md` (modify) — status row.

**Out of scope** (do NOT touch, even though they look related):

- `tools/sim_cleanup.py` — do **not** add `ros2 bag`/`rosbag2` to its kill list.
  The recorder is stopped via its own pidfile group; the allow-list killer stays
  untouched. (See its header comment, `sim_cleanup.py:23-30`.)
- PX4 ULog retrieval — that is plan **010** (design follow-up #2). Do not copy or
  touch any `*.ulg` here.
- `just analyze` / any skein invocation — that is plan **011**. Do not add a skein
  dependency or call skein anywhere.
- `hw()` and the e2e path (`_run_e2e_sim_group`, `test`) — do **not** add recording
  to them in this plan. (They route through `_teardown()`, which must remain safe
  when no recorder is running — see Step 3.)
- Bag rotation / size caps / segment splitting — deferred (design open-question 3).
  If a long run grows the bag, that is acceptable for now; do **not** add rotation.

## Git workflow

- Branch: `advisor/009-record-ros2-bag-during-sim` (repo convention: prior plans
  merged from `advisor/NNN-<slug>` branches).
- Commit message style: conventional commits, matching `git log` (e.g.
  `feat(sim): record a ROS 2 MCAP bag during just sim`).
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Create `tools/bag_recorder.py` with a testable recorder lifecycle

Create `tools/bag_recorder.py`. It must be importable and unit-testable without
ROS by keeping the OS primitives in monkeypatch-able module functions (mirror
`sim_cleanup.py`). Target shape:

```python
#!/usr/bin/env python3
"""Per-run ROS 2 MCAP bag recorder for `just sim`.

Starts `ros2 bag record` detached in its own process group, writing an MCAP bag
under logs/runs/<run-id>/bag/. Stops it with SIGINT (graceful — required so the
open MCAP is finalized, not truncated) and only SIGKILLs the group as a last
resort. Recording is best-effort: a failure here never aborts the sim.
"""

from __future__ import annotations

import os
import shlex
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = ROOT / "logs"
RUNS_DIR = LOG_DIR / "runs"
BAG_PIDFILE = LOG_DIR / "bag.pid"

# Subset of docs/TOPICS.md recorded for cross-clock analysis. /clock feeds skein's
# SIM_ELAPSED domain; vehicle_local_position is the common signal skein
# cross-correlates against the PX4 ULog for PX4_BOOT alignment. Keep in sync with
# docs/TOPICS.md (this is the minimum useful set, not `-a`).
_BAG_TOPICS: list[str] = [
    "/clock",
    "/fmu/out/vehicle_local_position_v1",
    "/fmu/out/vehicle_status_v1",
    "/fmu/in/trajectory_setpoint",
    "/fmu/in/offboard_control_mode",
    "/fmu/in/vehicle_command",
    "/drone/odom",
    "/drone/target_pose",
    "/drone/mission_status",
]


def _ros_setup_path() -> str:
    return os.environ.get("ROS_SETUP", "/opt/ros/jazzy/setup.bash")


def new_run_dir(now: datetime | None = None) -> Path:
    """Create and return logs/runs/<YYYYmmdd_HHMMSS>/ and update the
    logs/runs/latest symlink to point at it."""
    run_id = (now or datetime.now()).strftime("%Y%m%d_%H%M%S")
    run_dir = RUNS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    latest = RUNS_DIR / "latest"
    try:
        if latest.is_symlink() or latest.exists():
            latest.unlink()
        latest.symlink_to(run_id)  # relative target
    except OSError:
        pass
    return run_dir


def _record_argv(run_dir: Path, topics: list[str]) -> list[str]:
    """A `bash -lc` that sources ROS (+ workspace if built), then EXECs
    `ros2 bag record` so SIGINT to the process group reaches ros2 directly."""
    ros_setup = _ros_setup_path()
    ws_setup = ROOT / "install" / "setup.bash"
    sources = [f"source {shlex.quote(ros_setup)}"]
    if ws_setup.exists():
        sources.append(f"source {shlex.quote(str(ws_setup))}")
    rec = (
        "ros2 bag record -s mcap -o "
        + shlex.quote(str(run_dir / "bag"))
        + " "
        + " ".join(shlex.quote(t) for t in topics)
    )
    inner = " && ".join([*sources, f"exec {rec}"])
    return ["bash", "-lc", inner]


def start(
    run_dir: Path,
    env: dict[str, str],
    *,
    topics: list[str] | None = None,
    spawn=subprocess.Popen,
) -> "subprocess.Popen[bytes] | None":
    """Spawn the detached recorder into its own setsid group; record its pid in
    logs/bag.pid. Best-effort: returns None and prints a warning on failure
    (never raises, so a missing mcap storage plugin can't abort the sim)."""
    topics = topics or _BAG_TOPICS
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_fh = (run_dir / "bag_record.log").open("w", encoding="utf-8")
    try:
        proc = spawn(
            _record_argv(run_dir, topics),
            env=env,
            stdout=log_fh,
            stderr=subprocess.STDOUT,
            preexec_fn=os.setsid,
            cwd=str(ROOT),
        )
    except Exception as e:  # noqa: BLE001 - recording is best-effort
        print(f"Warning: bag recorder failed to start: {e}", file=sys.stderr)
        return None
    BAG_PIDFILE.write_text(str(proc.pid))
    return proc


def _getpgid(pid: int) -> int:
    return os.getpgid(pid)


def _killpg(pgid: int, sig: int) -> None:
    try:
        os.killpg(pgid, sig)
    except (ProcessLookupError, PermissionError):
        pass


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def stop(*, timeout: float = 15.0) -> bool:
    """SIGINT the recorder's process group and wait up to `timeout`s for it to
    finalize the MCAP. SIGKILL the group only as a last resort. Returns True if
    it stopped cleanly (or nothing was recording). Never raises."""
    if not BAG_PIDFILE.exists():
        return True
    try:
        pid = int(BAG_PIDFILE.read_text().strip())
    except (ValueError, OSError):
        BAG_PIDFILE.unlink(missing_ok=True)
        return True
    try:
        pgid = _getpgid(pid)
    except ProcessLookupError:
        BAG_PIDFILE.unlink(missing_ok=True)
        return True

    _killpg(pgid, signal.SIGINT)
    deadline = time.monotonic() + timeout
    clean = False
    while time.monotonic() < deadline:
        if not _alive(pid):
            clean = True
            break
        time.sleep(0.2)
    if not clean:
        _killpg(pgid, signal.SIGKILL)
    BAG_PIDFILE.unlink(missing_ok=True)
    return clean
```

Notes that are load-bearing:

- **`exec`** in `_record_argv` matters: it replaces the bash shell with the
  `ros2` process inside the setsid group, so the SIGINT in `stop()` reaches
  `ros2 bag record` directly and it writes the MCAP footer/index cleanly.
- **`-s mcap`** selects the MCAP storage plugin (`ros-jazzy-rosbag2-storage-mcap`).
  `ros2 bag record -o <dir>` always produces a **directory** named `<dir>` (here
  `logs/runs/<run-id>/bag/`) containing `metadata.yaml` and a `bag_0.mcap`. That
  inner `.mcap` is the file skein ingests; this plan does not rename it.

**Verify**: `uv run ruff check tools/bag_recorder.py` → exit 0; and
`uv run ty check tools/ --exclude tools/gcs_heartbeat.py` → exit 0.

### Step 2: Start the recorder in `sim()` after readiness is confirmed

In `tasks.py`, add `import bag_recorder` alongside the other `tools/` imports
(near `import sim_cleanup`, `tasks.py:158`).

In `sim()`, after the `wait_ready.py` gate **passes** (i.e. after the
`if res.returncode != 0:` block that tears down on failure) and before/at the
`format_ready(...)` print, start the recorder. The flight happens after
readiness, so recording from this point captures it. Target shape:

```python
    # readiness confirmed past this point
    run_dir = bag_recorder.new_run_dir()
    bag_proc = bag_recorder.start(run_dir, env)
    rec_detail = (
        f"recording -> {run_dir.relative_to(ROOT)}/bag"
        if bag_proc is not None
        else "recording: DISABLED (recorder failed to start)"
    )
    print(
        format_ready(
            ["/fmu topics up", "rosbridge:9090", "GCS params committed", rec_detail],
            elapsed,
        )
    )
```

Reuse the **same `env`** already built for `_spawn_stack` in `sim()` (the
`_ros_launch_env(...)` result) so the recorder child has the same PATH/GZ env;
`_record_argv` adds the ROS `source` on top.

Do **not** add recording to the failed-launch path, to `hw()`, or to
`_run_e2e_sim_group` (out of scope).

**Verify**: `uv run ruff check tasks.py` → exit 0;
`uv run python -c "import sys; sys.path.insert(0,'tools'); import bag_recorder; print('ok')"`
→ prints `ok`.

### Step 3: Stop the recorder first in `_teardown()`

In `tasks.py`, change `_teardown()` to stop the recorder gracefully **before**
the SIGKILL sweep:

```python
def _teardown() -> bool:
    """Exhaustive cold teardown of the whole stack. Prints a STOPPED verdict."""
    bag_recorder.stop()  # graceful SIGINT first; finalizes the MCAP. Non-fatal.
    result = sim_cleanup.teardown()
    print(format_stopped(result["killed"], result["survivors"]))
    return not result["survivors"]
```

This is the single funnel used by `stop()`, failed launches, and e2e boundaries.
When no recorder is running, `bag_recorder.stop()` finds no `logs/bag.pid` and
returns immediately (no-op) — so the e2e and hw paths are unaffected.

**Verify**: `uv run ruff check tasks.py` → exit 0.

### Step 4: Unit-test `bag_recorder` (no ROS required)

Create `tests/unit/test_bag_recorder.py`, modeled structurally on
`tests/unit/test_sim_cleanup.py` (sys.path insert of `tools/`, monkeypatch of
module-level primitives, fake/injected callables). Cover at least:

1. `_record_argv` builds the expected command: result is `["bash", "-lc", inner]`,
   and `inner` contains `ros2 bag record -s mcap -o`, ends with the topics, and
   contains `exec ` and a `source` of the ROS setup. (Pure function — no mocks.)
2. `_BAG_TOPICS` includes `/clock` and `/fmu/out/vehicle_local_position_v1` (the
   two skein-critical channels).
3. `start(...)` writes `logs/bag.pid` and calls `spawn` with `preexec_fn` set:
   inject a fake `spawn` returning an object with a `.pid`, point `BAG_PIDFILE`
   at a `tmp_path` via monkeypatch, assert the pidfile contains that pid.
4. `start(...)` returns `None` and does not raise when `spawn` raises (best-effort
   contract): inject a `spawn` that raises.
5. `stop()` returns `True` immediately (no kill) when the pidfile is absent.
6. `stop()` SIGINTs the group and returns `True` when the process dies within
   timeout: monkeypatch `_getpgid` → fixed pgid, `_killpg` → record calls,
   `_alive` → return False (or True once then False); use a tiny `timeout`.
   Assert a SIGINT (`signal.SIGINT`) call was recorded and **no** SIGKILL.
7. `stop()` escalates to SIGKILL and returns `False` when the process never dies:
   `_alive` always True, tiny `timeout`; assert both SIGINT and SIGKILL recorded.

Use `monkeypatch.setattr(bag_recorder, "BAG_PIDFILE", tmp_path / "bag.pid")` to
keep tests off the real `logs/`.

**Verify**: `uv run pytest tests/unit/test_bag_recorder.py -q` → all pass.

### Step 5: Run the full unit suite and quality gate

**Verify**:
- `uv run pytest tests/unit/ -q --tb=short` → all pass (existing + new).
- `just check` → exits 0, prints "all checks passed." (If ROS/colcon is
  unavailable in this environment, run `uv run ruff check`, the `ty` command, and
  the pytest command from the table individually and report that the colcon build
  step could not run here — do **not** mark live sim verification as done.)

## Test plan

- New file `tests/unit/test_bag_recorder.py`, structured like
  `tests/unit/test_sim_cleanup.py`, covering the 7 cases in Step 4 (argv shape,
  topic set, pidfile write, best-effort start failure, no-op stop, graceful
  SIGINT stop, SIGKILL escalation).
- No new tests for `tasks.py` wiring (it orchestrates subprocesses; the logic
  under test lives in `bag_recorder`). The `sim()`/`_teardown()` edits are
  covered by the live sim verification below.
- Verification: `uv run pytest tests/unit/ -q` → all pass, including the new
  `test_bag_recorder.py` cases.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `tools/bag_recorder.py` exists; `uv run ruff check tools/bag_recorder.py tasks.py` exits 0.
- [ ] `uv run ty check tools/ --exclude tools/gcs_heartbeat.py` exits 0.
- [ ] `uv run pytest tests/unit/ -q` exits 0; `tests/unit/test_bag_recorder.py` exists and its cases pass.
- [ ] `grep -n "import bag_recorder" tasks.py` matches; `grep -n "bag_recorder.stop()" tasks.py` matches inside `_teardown`.
- [ ] `tools/sim_cleanup.py` is **unchanged** (`git diff --stat 3b904a5..HEAD -- tools/sim_cleanup.py` shows nothing).
- [ ] No files outside the in-scope list are modified (`git status`).
- [ ] `plans/README.md` status row for 009 updated.

Live (SITL) verification — perform if a distrobox sim is available; otherwise
report it as deferred to the maintainer (do not fake it):

- [ ] `just sim --overlay auto_arm` reaches READY and its verdict shows `recording -> logs/runs/.../bag`.
- [ ] A non-empty `logs/runs/<id>/bag/*.mcap` exists after a few seconds of flight.
- [ ] `just stop` prints STOPPED with no `ros2`/`rosbag2` survivor, and `logs/bag.pid` is gone.
- [ ] (Cross-repo smoke) the recorded MCAP is ingestible:
      `cd /home/ivy/Projects/skein && uv run skein query <abs path to that .mcap> -c vehicle_local_position --stats`
      returns rows (proves skein can read the bag). This only reads the bag; it
      changes nothing in either repo.

## STOP conditions

Stop and report back (do not improvise) if:

- The "Current state" excerpts for `tasks.py` (`_teardown`, the `sim()` readiness
  block) or `sim_cleanup.py` don't match the live code (drift since `3b904a5`).
- `ros2 bag record -s mcap` fails because the MCAP storage plugin is missing
  (`ros-jazzy-rosbag2-storage-mcap` not installed). Do **not** apt-install it
  yourself or silently fall back to sqlite3 storage — report it; skein needs MCAP.
- Implementing this appears to require modifying `tools/sim_cleanup.py` (it does
  not — the recorder is self-contained via its pidfile group). If you reach for
  it, stop.
- A step's verification fails twice after a reasonable fix attempt.
- You discover the assumption "`ros2 bag record -o <dir>` produces a directory
  containing a single `*.mcap`" is false on this ROS distro (e.g. it writes a
  bare file or splits by default) — report what it actually produced.

## Maintenance notes

For whoever owns this next:

- **ULog pairing (plan 010)** will copy the matching PX4 SITL `*.ulg` into the
  same `logs/runs/<id>/` so a run pairs a bag with its ULog. It will rely on the
  `logs/runs/<id>/` layout and the `logs/runs/latest` symlink created here.
- **`just analyze` (plan 011)** will point `skein overlay --bag` at
  `logs/runs/<id>/bag/<the .mcap>`. Remember the bag is a *directory*; the
  ingestible file is the inner `*.mcap`.
- **Topic drift**: `_BAG_TOPICS` mirrors `docs/TOPICS.md`. If a topic is renamed
  there (PX4 version bump changing the `_v1` suffix, etc.), update `_BAG_TOPICS`
  too, or the bag silently misses it. A future hardening is to derive the list
  from `docs/TOPICS.md` via the existing `tools/check_topics.py` parser instead of
  hardcoding — deliberately deferred to keep this plan tight.
- **Disk / rotation**: long interactive `just sim` sessions grow the bag
  unbounded (no rotation/size cap — deferred, design open-question 3). If this
  bites, add `--max-bag-size`/`--max-bag-duration` to the `ros2 bag record` argv.
- **Reviewer focus**: confirm `tools/sim_cleanup.py` was not touched; confirm the
  recorder is SIGINT'd *before* `sim_cleanup.teardown()` in `_teardown()`; confirm
  recording can never abort `just sim` (start is best-effort, returns None on
  failure).
