# Plan 032: Scenario FAIL reports carry real diagnostics (trigger failures surfaced; rich detail in 02 and 05)

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report - do not improvise. When done, update the status row for this plan
> in `plans/README.md` - unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat ead4cc6..HEAD -- tests/scenarios/`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: dx
- **Planned at**: commit `ead4cc6`, 2026-07-06

## Why this matters

This template's core promise is that an AI agent can run `just scenario <name>`
and diagnose a failure from the report. Two gaps break that promise:

1. `_common._ros2()` wraps the `ros2 param set ... auto_arm true` arm trigger
   (and the cleanup land) in `except Exception: pass`. If `ros2` is missing
   from PATH or the param set is rejected, the scenario fails later as a
   generic `timeout` and the agent debugs a phantom flight problem instead of
   a broken trigger.
2. Scenarios 02 and 05 fail with bare `{"reason": "climb_timeout"}` /
   `{"reason": "timeout"}`, while 01/03/06 capture pose, state, and counters.
   A FAIL from 02/05 cannot distinguish "never armed" from "climbed to 2 m and
   stalled" from "no marker detection ever arrived".

Repo doctrine (AGENTS.md, Code changes section): each scenario "must end by
calling `_common.write_report` ... pass a real `detail` (waypoint error, hold
time, or the fail reason), never a bare pass". This plan applies the same
standard to failures.

## Current state

- `tests/scenarios/_common.py` - shared helpers; the swallow is at lines 29-42.
- `tests/scenarios/02_hover_hold.py` - sparse climb-timeout detail (lines 60-65).
- `tests/scenarios/05_aruco_hover.py` - sparse timeout detail (lines 187-193).
- `tests/scenarios/01_arm_takeoff.py` - the exemplar for rich failure detail
  (its FAIL path captures pose/state/phase; model the new detail on it).

The swallow (`tests/scenarios/_common.py:29-42`):

```python
    """Run a ros2 CLI command, sourcing the ROS2 setup if ros2 is not already on PATH."""
    import shutil
    import subprocess

    if shutil.which("ros2"):
        cmd = ["ros2", *args]
    else:
        ros2_args = " ".join(f'"{a}"' for a in args)
        cmd = ["bash", "-c", f"source /opt/ros/jazzy/setup.bash 2>/dev/null && ros2 {ros2_args}"]
    try:
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=timeout)
    except Exception:
        pass


def trigger_auto_arm() -> None:
    """Dynamically enable auto-arming on the running offboard_controller for scenario execution."""
    _ros2("param", "set", "/offboard_controller", "auto_arm", "true")
```

Scenario 02 FAIL path (`tests/scenarios/02_hover_hold.py:59-65`); the node
tracks `node.x`, `node.y`, `node.z` (ENU from `/fmu/out/vehicle_local_position_v1`):

```python
        except TimeoutError:
            console.print("[red]✗ FAIL — never reached target altitude[/red]")
            write_report(
                "02_hover_hold", False, time.monotonic() - started, {"reason": "climb_timeout"}
            )
            return False
```

Scenario 05 FAIL path (`tests/scenarios/05_aruco_hover.py:189-193`); the node
tracks `node.entered_marker_hover`, `node.target_pose`, `node.mission_done`:

```python
        except TimeoutError:
            elapsed = time.monotonic() - started
            console.print(f"[red]✗ FAIL — timeout after {timeout_s}s[/red]")
            write_report("05_aruco_hover", False, elapsed, {"reason": "timeout"})
            return False
```

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Lint | `uv run ruff check tests/scenarios/` | exit 0 |
| Full gate | `just check` | exit 0 |
| Live check (operator, distrobox) | `just scenario 02_hover_hold` | PASS verdict, exit 0 |

Note: scenario files import `rclpy` and cannot be unit-tested on a bare host;
verification is lint + the live run.

## Scope

**In scope**:
- `tests/scenarios/_common.py`
- `tests/scenarios/02_hover_hold.py`
- `tests/scenarios/05_aruco_hover.py`

**Out of scope**:
- `tests/scenarios/01_arm_takeoff.py`, `03_waypoint.py`, `06_search_relocalize.py` -
  already rich; do not churn them.
- `tools/e2e_report.py`, `tools/scenario_status.py` - they render whatever
  `detail` contains; no changes needed.
- Changing any PASS predicate or timeout value.

## Git workflow

- Branch: `advisor/032-scenario-failure-reporting`
- Commit style: `fix(scenarios): surface trigger failures and enrich 02/05 FAIL detail`
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Make `_ros2` report success/failure

In `tests/scenarios/_common.py`, change `_ros2` to return a bool instead of
swallowing silently:

```python
    try:
        res = subprocess.run(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=timeout
        )
        return res.returncode == 0
    except Exception:
        return False
```

Update its type annotation (`-> bool`) and docstring. Then:

- `trigger_auto_arm() -> bool`: return the `_ros2(...)` result, and if it is
  False, print a clearly-attributed warning so it lands in the scenario output:
  `print("[scenario] WARN: auto_arm trigger failed (ros2 param set)", flush=True)`.
- `trigger_cleanup()`: keep returning None, but if either `_ros2` call returns
  False, print `"[scenario] WARN: cleanup trigger failed"` the same way.

**Verify**: `uv run ruff check tests/scenarios/_common.py` -> exit 0

### Step 2: Record the trigger result in every scenario that fails

In `02_hover_hold.py` and `05_aruco_hover.py`, capture
`arm_trigger_ok = trigger_auto_arm()` at the existing call site and include it
in the FAIL detail dicts written in the next steps. (01/03/06 are out of scope;
their call sites keep working because `trigger_auto_arm` still performs the
same action.)

**Verify**: `uv run ruff check tests/scenarios/` -> exit 0

### Step 3: Enrich scenario 02's climb-timeout detail

Replace the detail dict with:

```python
                {
                    "reason": "climb_timeout",
                    "z_enu_m": round(node.z, 2),
                    "xy_enu_m": [round(node.x, 2), round(node.y, 2)],
                    "climb_threshold_m": _CLIMB_THRESHOLD,
                    "arm_trigger_ok": arm_trigger_ok,
                }
```

Also check 02's other FAIL paths (drift violation / hold failure later in the
file): each should already carry positional detail; if any writes a bare
`{"reason": ...}`, add the same `z_enu_m`/`xy_enu_m`/`arm_trigger_ok` fields.

**Verify**: `uv run ruff check tests/scenarios/02_hover_hold.py` -> exit 0

### Step 4: Enrich scenario 05's timeout detail

Replace the detail dict with:

```python
                {
                    "reason": "timeout",
                    "entered_marker_hover": node.entered_marker_hover,
                    "target_pose_seen": node.target_pose is not None,
                    "mission_done": node.mission_done,
                    "arm_trigger_ok": arm_trigger_ok,
                }
```

Read `_ScenarioNode` in the same file first: if it tracks additional state
useful at timeout (e.g. a mission phase string or a detection counter), include
it; do not add new subscriptions.

**Verify**: `uv run ruff check tests/scenarios/05_aruco_hover.py` -> exit 0

### Step 5: Full gate + live run

**Verify**: `just check` -> exit 0.
Then (operator, ROS-capable shell): `just scenario 02_hover_hold` -> PASS.
Confirm `logs/scenario_02_hover_hold.json` exists and, on a PASS, is unchanged
in shape. If you cannot run a sim, STOP after `just check` and report live
verification pending.

## Test plan

No new unit tests (scenario files need a live ROS graph; the repo runs them via
`just scenario`/`just test e2e`). The behavioral check is the live run in
Step 5 plus lint. `tools/scenario_status.py` and `e2e_report.py` render
arbitrary detail dicts, so no downstream changes.

## Done criteria

- [ ] `rg -n "except Exception:\s*$" -A1 tests/scenarios/_common.py` shows no `pass` in `_ros2` (it returns False)
- [ ] `rg -n "arm_trigger_ok" tests/scenarios/02_hover_hold.py tests/scenarios/05_aruco_hover.py` -> at least one match per file
- [ ] `rg -n '\{"reason": "timeout"\}' tests/scenarios/05_aruco_hover.py` -> no matches
- [ ] `just check` exits 0
- [ ] `git status` shows only in-scope files modified
- [ ] `plans/README.md` status row updated

## STOP conditions

- The `_ScenarioNode` field names in 02/05 differ from the excerpts (drift).
- Any PASS-path behavior would need to change to satisfy a step.
- `just scenario 02_hover_hold` fails on the PASS path after your change
  (something in the trigger refactor altered behavior, not just reporting).

## Maintenance notes

- Plan 033 prints a failure digest from the session log at the `tasks.py`
  level; this plan's detail enrichment is complementary (per-scenario JSON).
- Future scenarios scaffolded by `just scenario-new` should follow the same
  rule: never write a bare `{"reason": ...}` on FAIL. Consider updating the
  scaffold template if this recurs (deferred; not in scope here).
