# Plan 010: Retrieve the matching PX4 SITL ULog into the run directory at teardown

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**:
> `git diff --stat 3b904a5..HEAD -- tasks.py tools/bag_recorder.py`
> This plan **depends on plan 009 being merged first** (it uses
> `tools/bag_recorder.py` and the `logs/runs/<id>/` layout 009 introduced). If
> `tools/bag_recorder.py` does not exist on HEAD, STOP — 009 has not landed yet.
> If `tasks.py`'s `_teardown()` does not already call `bag_recorder.stop()`,
> STOP and report (the 009 integration is missing or changed).

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MED (touches the shared `_teardown()` funnel; retrieval must never break teardown)
- **Depends on**: `plans/009-record-ros2-bag-during-sim.md` (MUST be merged to `main` first)
- **Category**: direction (integration enablement)
- **Planned at**: commit `3b904a5`, 2026-06-22

## Why this matters

skein's offline `overlay` needs **two artifacts per run**: a ROS 2 MCAP bag *and*
the matching PX4 ULog (`*.ulg`). Plan 009 produces the bag at
`logs/runs/<run-id>/bag/`; this plan produces the ULog beside it at
`logs/runs/<run-id>/session.ulg`, so each run is a self-contained skein input
pair. This is follow-up **#2** of the integration design at
`/home/ivy/Projects/skein/docs/template-integration-design.md` (§3b, open
question 1).

PX4 SITL writes its own ULog under the firmware tree; nothing copies it into the
template's `logs/` today. This plan copies the **run's** ULog at teardown, using a
freshness guard so a *stale ULog from a previous boot* can never be mistaken for
this run's (design open question 1). Retrieval is **best-effort and SITL-only**:
it never fails teardown, and it does not apply to hardware (a real flight
controller logs to its SD card, not to `$PX4_DIR/.../rootfs/log`).

## Current state

Files involved (post-009 — confirm 009 is merged via the drift check above):

- `tasks.py`:
  - `_load_dotenv()` loads `.env` into `os.environ` at import time, so
    `os.environ["PX4_DIR"]` is available (`tasks.py:37-52`). The repo `.env`
    sets `PX4_DIR=/home/ivy/robotics/PX4-Autopilot` (a path, read by `setup()` at
    `tasks.py:281`). Do not hardcode that path — read `os.environ.get("PX4_DIR")`.
  - `_teardown()` — the single teardown funnel (stop / failed launch / e2e
    boundary). **After 009 it looks like this** (`tasks.py`, around `:181-186`):
    ```python
    def _teardown() -> bool:
        bag_recorder.stop()  # graceful SIGINT first; finalizes the MCAP. Non-fatal.
        result = sim_cleanup.teardown()
        print(format_stopped(result["killed"], result["survivors"]))
        return not result["survivors"]
    ```
    `sim_cleanup.teardown()` SIGKILLs PX4 and the whole stack. The ULog must be
    copied **after** that call, so PX4 has stopped writing and the `.ulg` is final.
  - `import bag_recorder` is already present near the other `tools/` imports
    (added by 009, ~`tasks.py:159`). Add `import ulog_retrieve` the same way.

- `tools/bag_recorder.py` (created by 009) — provides the run layout this plan
  reuses. Relevant module constants and the lifecycle signal:
  ```python
  RUNS_DIR = LOG_DIR / "runs"          # logs/runs/
  BAG_PIDFILE = LOG_DIR / "bag.pid"    # exists while/just-after a recording session
  def new_run_dir(...) -> Path: ...    # creates logs/runs/<YYYYmmdd_HHMMSS>/ + a `latest` symlink
  def stop(*, timeout=15.0) -> bool: ...   # removes BAG_PIDFILE
  ```
  `logs/runs/latest` is a symlink to the current run dir; `BAG_PIDFILE` existing
  at the *start* of `_teardown()` is the signal that this teardown is ending a
  recorded `just sim` run (the e2e and `hw` paths never start the recorder, so it
  is absent there).

- The PX4 SITL ULog path (confirmed present on this machine):
  `$PX4_DIR/build/px4_sitl_default/rootfs/log/<YYYY-MM-DD>/<HH_MM_SS>.ulg`
  e.g. `/home/ivy/robotics/PX4-Autopilot/build/px4_sitl_default/rootfs/log/2026-06-21/09_38_34.ulg`.
  The `.ulg` is appended throughout the flight, so at teardown its `st_mtime` is
  recent (end of flight). A ULog from a *prior* boot has a frozen, older mtime.

- `tests/unit/test_bag_recorder.py` (created by 009) and
  `tests/unit/test_sim_cleanup.py` — the **structural patterns** for the new test:
  `sys.path.insert(0, .../tools)`, import the module by bare name, build fake
  inputs in `tmp_path`, inject side-effecting callables, monkeypatch module
  primitives.

Conventions to match:

- Tools live in `tools/`, importable, side-effecting primitives in small
  module-level functions so tests can monkeypatch/inject them (see
  `bag_recorder.py`, `sim_cleanup.py`).
- Python ≥ 3.12, `from __future__ import annotations`, type hints throughout.
- Best-effort I/O helpers print a `Warning: ...` to stderr and return a sentinel
  (`None`) rather than raising — mirror `bag_recorder.start()`'s contract.

## Commands you will need

| Purpose            | Command                                                        | Expected on success                |
|--------------------|----------------------------------------------------------------|------------------------------------|
| Lint new file      | `uv run ruff check tools/ulog_retrieve.py`                     | exit 0; "All checks passed!"       |
| Typecheck          | `uv run ty check tools/ --exclude tools/gcs_heartbeat.py`      | exit 0; "All checks passed!"       |
| New test only      | `uv run pytest tests/unit/test_ulog_retrieve.py -q`            | all pass                           |
| Full unit suite    | `uv run pytest tests/unit/ -q --tb=short`                      | all pass (see note)                |

Note on the suite: `tests/unit/test_scenario_verdict.py` fails to *collect* on a
machine without `rclpy` (`ModuleNotFoundError: No module named 'rclpy'`) — this is
**pre-existing**, unrelated to this plan. If you hit it, re-run with
`--ignore=tests/unit/test_scenario_verdict.py` and note it; do not try to fix it.

`just check`'s ruff gate lints `["src/core", "tests", "tools", "sim", "hardware"]`
(`tasks.py:386`) — it covers your new `tools/` and `tests/` files but **not**
`tasks.py` itself. Do not attempt to clean pre-existing `tasks.py` lint findings;
they are out of scope. If ROS/colcon is unavailable here, run the table commands
individually instead of `just check` and report the colcon/live steps as deferred.

## Scope

**In scope** (the only files you should modify or create):

- `tools/ulog_retrieve.py` (create) — find + copy the run's ULog.
- `tasks.py` (modify) — `import ulog_retrieve`; in `_teardown()`, after
  `sim_cleanup.teardown()`, copy the ULog when a recording session was active.
- `tests/unit/test_ulog_retrieve.py` (create) — unit tests.
- `plans/README.md` (modify) — status row.

**Out of scope** (do NOT touch, even though they look related):

- `tools/bag_recorder.py` and `tools/sim_cleanup.py` — do not modify; only import
  `bag_recorder` for its `RUNS_DIR`/`BAG_PIDFILE` constants.
- `hw()` — hardware ULogs do not live under `$PX4_DIR/.../rootfs/log`; SITL-only
  here. (Retrieval is gated on `BAG_PIDFILE`, which `hw()` never creates, so it
  won't fire — but also do not add any hardware ULog logic.)
- `just analyze` / any skein invocation — that is plan **011**.
- Trimming/filtering the ULog (the golden fixture trims to 3 message types) —
  out of scope; copy the full `.ulg` verbatim.
- Deleting or rotating PX4's own ULogs — never touch the firmware tree's files;
  **copy**, do not move.

## Git workflow

- Branch: `advisor/010-retrieve-px4-sitl-ulog-at-teardown` (repo convention:
  `advisor/NNN-<slug>`).
- Commit message style: conventional commits, e.g.
  `feat(sim): copy the run's PX4 SITL ULog into logs/runs/<id> at teardown`.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Create `tools/ulog_retrieve.py`

Create the module. Keep `find_latest_ulog` a pure function over a directory (for
unit tests) and `retrieve` the best-effort orchestrator. Target shape:

```python
#!/usr/bin/env python3
"""Copy the current run's PX4 SITL ULog into its logs/runs/<id>/ directory.

SITL-only and best-effort: PX4 SITL writes ULogs under
$PX4_DIR/build/px4_sitl_default/rootfs/log/<date>/<time>.ulg. At teardown of a
recorded `just sim` run we copy the newest ULog that was written during this run
to logs/runs/<id>/session.ulg, so a run pairs its bag with its ULog for skein.

A freshness guard (mtime >= the run dir's start time) prevents a stale ULog from
a previous boot from being mistaken for this run's. Never raises — a miss leaves
the run without a ULog and warns, rather than failing teardown.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

_SITL_LOG_SUBPATH = "build/px4_sitl_default/rootfs/log"


def _px4_log_root(px4_dir: str | None) -> Path | None:
    px4_dir = px4_dir if px4_dir is not None else os.environ.get("PX4_DIR", "").strip()
    if not px4_dir:
        return None
    root = Path(px4_dir) / _SITL_LOG_SUBPATH
    return root if root.is_dir() else None


def find_latest_ulog(log_root: Path, *, since_mtime: float) -> Path | None:
    """Return the newest *.ulg under log_root whose mtime is >= since_mtime, or
    None if there is no such (fresh) ULog. Pure over the filesystem under log_root."""
    candidates: list[tuple[float, Path]] = []
    for ulg in log_root.rglob("*.ulg"):
        try:
            mtime = ulg.stat().st_mtime
        except OSError:
            continue
        if mtime >= since_mtime:
            candidates.append((mtime, ulg))
    if not candidates:
        return None
    return max(candidates, key=lambda t: t[0])[1]


def retrieve(
    run_dir: Path,
    *,
    px4_dir: str | None = None,
    copy=shutil.copy2,
) -> Path | None:
    """Copy the run's PX4 SITL ULog into run_dir/session.ulg. Returns the
    destination path on success, else None. Best-effort: never raises."""
    try:
        resolved = run_dir.resolve()  # run_dir may be the logs/runs/latest symlink
        if not resolved.is_dir():
            print(f"Warning: ULog retrieval skipped — no run dir at {run_dir}", file=sys.stderr)
            return None
        log_root = _px4_log_root(px4_dir)
        if log_root is None:
            print(
                "Warning: ULog retrieval skipped — PX4_DIR unset or "
                f"{_SITL_LOG_SUBPATH} missing (SITL-only).",
                file=sys.stderr,
            )
            return None
        since = resolved.stat().st_mtime
        src = find_latest_ulog(log_root, since_mtime=since)
        if src is None:
            print(
                "Warning: no fresh PX4 ULog found for this run under "
                f"{log_root} (SITL may not have logged this run).",
                file=sys.stderr,
            )
            return None
        dest = resolved / "session.ulg"
        copy(str(src), str(dest))
        print(f"Copied PX4 ULog {src.name} -> {dest.relative_to(resolved.parent.parent.parent)}")
        return dest
    except Exception as e:  # noqa: BLE001 - retrieval is best-effort, never fatal
        print(f"Warning: ULog retrieval failed: {e}", file=sys.stderr)
        return None
```

Notes:

- **`since_mtime = run_dir.stat().st_mtime`** is the freshness anchor: the run dir
  was created at sim readiness (start of the recorded window), so the run's own
  ULog — appended through the flight — has a newer mtime and is selected, while a
  prior-boot ULog (frozen mtime, older than this run dir) is excluded.
- The final `print(... relative_to ...)` is cosmetic; if `relative_to` raises
  because the path isn't under `logs/`, the outer `except` swallows it and still
  returns `dest` would be lost — so keep the print **simple**; if you're unsure,
  print `dest` plainly (`print(f"Copied PX4 ULog -> {dest}")`) rather than risk
  the relative-path computation. Correctness of the copy matters; the log line
  does not.

**Verify**: `uv run ruff check tools/ulog_retrieve.py` → exit 0;
`uv run ty check tools/ --exclude tools/gcs_heartbeat.py` → exit 0.

### Step 2: Wire retrieval into `_teardown()` after the kill sweep

In `tasks.py`, add `import ulog_retrieve` next to `import bag_recorder`.

Change `_teardown()` so it (a) records whether a recording session was active
*before* `bag_recorder.stop()` removes the pidfile, and (b) copies the ULog
*after* `sim_cleanup.teardown()` has killed PX4 (so the `.ulg` is final):

```python
def _teardown() -> bool:
    """Exhaustive cold teardown of the whole stack. Prints a STOPPED verdict."""
    was_recording = bag_recorder.BAG_PIDFILE.exists()
    bag_recorder.stop()  # graceful SIGINT first; finalizes the MCAP. Non-fatal.
    result = sim_cleanup.teardown()
    if was_recording:
        # PX4 is dead now, so its ULog is final. Best-effort, SITL-only.
        ulog_retrieve.retrieve(bag_recorder.RUNS_DIR / "latest")
    print(format_stopped(result["killed"], result["survivors"]))
    return not result["survivors"]
```

Do not change the failed-launch, `hw()`, or e2e call sites — they all route
through `_teardown()`, and `was_recording` is False there (no recorder started),
so retrieval is skipped automatically.

**Verify**: `uv run ruff check tasks.py` returns no *new* findings beyond the
pre-existing ones (the gate doesn't lint `tasks.py`; this is informational). And:
`uv run python -c "import sys; sys.path.insert(0,'tools'); import ulog_retrieve; print('ok')"`
→ prints `ok`.

### Step 3: Unit-test `ulog_retrieve` (no PX4 required)

Create `tests/unit/test_ulog_retrieve.py`, modeled on
`tests/unit/test_bag_recorder.py`. Build a fake PX4 log tree and run dir under
`tmp_path`, and set file mtimes with `os.utime`. Cover at least:

1. `find_latest_ulog` returns the **newest** `*.ulg` at/after `since_mtime`:
   create `a.ulg` (old), `b.ulg` (new), both under nested `<date>/` dirs; assert
   it returns `b.ulg`.
2. `find_latest_ulog` returns **None** when every `*.ulg` is older than
   `since_mtime` (the stale-prior-boot case).
3. `retrieve` copies the fresh ULog to `run_dir/session.ulg` and returns that
   path: make a `run_dir` (its `st_mtime` is "now"), a log root with one `.ulg`
   whose mtime you set to `run_dir.stat().st_mtime + 10`, pass `px4_dir` pointing
   at the fake PX4 dir, inject a recording `copy` (or use real `shutil.copy2` on
   the temp files). Assert `session.ulg` exists with the source's bytes.
4. `retrieve` returns **None** and copies nothing when no fresh ULog exists
   (all `.ulg` older than `run_dir` mtime).
5. `retrieve` returns **None** when `PX4_DIR`/log root is missing: pass
   `px4_dir=str(tmp_path / "nope")`.
6. `retrieve` never raises when `copy` raises (best-effort): inject a `copy` that
   raises `OSError`; assert it returns `None`.

Tip: to make a ULog "fresh", set its mtime strictly greater than
`run_dir.stat().st_mtime` (e.g. `os.utime(ulg, (t, t))` with
`t = run_dir.stat().st_mtime + 5`).

**Verify**: `uv run pytest tests/unit/test_ulog_retrieve.py -q` → all pass.

### Step 4: Run the unit suite

**Verify**:
- `uv run pytest tests/unit/ -q --tb=short` → all pass. (If
  `test_scenario_verdict.py` fails to collect with a `rclpy` ImportError, that is
  the pre-existing issue noted above — re-run with
  `--ignore=tests/unit/test_scenario_verdict.py` and report it.)

## Test plan

- New file `tests/unit/test_ulog_retrieve.py`, structured like
  `tests/unit/test_bag_recorder.py`, covering the 6 cases in Step 3 (newest-fresh
  selection, stale exclusion, happy-path copy, no-fresh → None, missing PX4_DIR →
  None, copy-raises → None).
- No new tests for the `tasks.py` `_teardown()` wiring (it orchestrates; the logic
  under test lives in `ulog_retrieve`). The wiring is covered by the live SITL
  verification below.
- Verification: `uv run pytest tests/unit/ -q` → all pass including the new file.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `tools/ulog_retrieve.py` exists; `uv run ruff check tools/ulog_retrieve.py` exits 0.
- [ ] `uv run ty check tools/ --exclude tools/gcs_heartbeat.py` exits 0.
- [ ] `tests/unit/test_ulog_retrieve.py` exists; `uv run pytest tests/unit/test_ulog_retrieve.py -q` passes.
- [ ] `uv run pytest tests/unit/ -q` passes (modulo the pre-existing `rclpy` collection error, if present).
- [ ] `grep -n "import ulog_retrieve" tasks.py` matches; `grep -n "ulog_retrieve.retrieve" tasks.py` matches inside `_teardown`.
- [ ] `ulog_retrieve.retrieve(...)` is called **after** `sim_cleanup.teardown()` in `_teardown()` (read the function — order matters).
- [ ] `tools/bag_recorder.py` and `tools/sim_cleanup.py` are unchanged (`git diff --stat HEAD~1..HEAD -- tools/bag_recorder.py tools/sim_cleanup.py` empty).
- [ ] No files outside the in-scope list are modified (`git status`).
- [ ] `plans/README.md` status row for 010 updated.

Live (SITL) verification — perform if a distrobox sim is available; otherwise
report it as deferred to the maintainer (do not fake it):

- [ ] `just sim --overlay auto_arm`, let it fly a few seconds, then `just stop`.
- [ ] `logs/runs/<id>/session.ulg` exists and is non-empty (and matches a recent
      ULog under `$PX4_DIR/build/px4_sitl_default/rootfs/log/`).
- [ ] Run `just stop` again immediately (no sim): teardown still succeeds and does
      not crash on the absent recorder (regression check for the `was_recording`
      guard).
- [ ] (Cross-repo smoke, optional) the pair is ingestible:
      `cd /home/ivy/Projects/skein && uv run skein overlay --bag <abs>/logs/runs/<id>/bag/bag_0.mcap --ulog <abs>/logs/runs/<id>/session.ulg --out /tmp/aligned.mcap`
      → writes `/tmp/aligned.mcap`. Reads only; changes nothing in either repo.

## STOP conditions

Stop and report back (do not improvise) if:

- `tools/bag_recorder.py` does not exist on HEAD, or `_teardown()` does not call
  `bag_recorder.stop()` — **plan 009 has not been merged**; this plan depends on it.
- The `_teardown()` excerpt in "Current state" doesn't match the live code
  (drift since 009 landed).
- Implementing this appears to require modifying `tools/bag_recorder.py`,
  `tools/sim_cleanup.py`, or `hw()`.
- A step's verification fails twice after a reasonable fix attempt.
- You discover the PX4 SITL ULog is **not** under
  `$PX4_DIR/build/px4_sitl_default/rootfs/log/**/*.ulg` on this machine (only
  checkable live — skip if not booting a sim; report what you find if you do).

## Maintenance notes

For whoever owns this next:

- **`just analyze` (plan 011)** will consume the pair this plan completes:
  `logs/runs/<id>/bag/<the .mcap>` (009) + `logs/runs/<id>/session.ulg` (010).
- **Freshness heuristic**: selection is "newest `*.ulg` with mtime >= the run
  dir's mtime." If PX4 rotates logs mid-run, the newest wins (the active log). If
  a future change moves run-dir creation earlier/later in `sim()`, re-check that
  the anchor still brackets the recorded window. A stricter alternative (parse the
  ULog header start time and match the bag's time span) was deliberately not done
  — too heavy for this step; revisit only if mis-pairing is observed.
- **Hardware**: when `just hw` recording is added (a later plan), the ULog comes
  off the flight controller's SD card / MAVLink log download, **not** from
  `$PX4_DIR/.../rootfs/log` — this module is SITL-only by construction.
- **Reviewer focus**: confirm the retrieve call is *after* `sim_cleanup.teardown()`
  (PX4 dead → final ULog); confirm `was_recording` is read *before*
  `bag_recorder.stop()` (which deletes the pidfile); confirm retrieval can never
  raise out of `_teardown()`; confirm PX4's own ULogs are copied, never moved.
