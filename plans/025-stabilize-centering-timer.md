# Plan 025: Stabilize Marker Centering Timer (CORRECTNESS-01)

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving on. If
> anything in "STOP conditions" occurs, stop and report. When done, update this
> plan's row in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat ead4cc6..HEAD -- src/core/ros_px4_template_core/lib/mission/behaviors.py`
> If it changed, compare the "Current state" excerpt to the live code before
> proceeding; on a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: correctness
- **Planned at**: commit `ead4cc6`, 2026-06-29

## Why this matters

The `center_on_marker` behavior aligns the drone over a target visual marker. However, minor sensor noise or state estimate fluctuations can cause the positioning error to momentarily exceed the tolerance threshold (`tolerance_m`, default 0.4m), which immediately clears the centering timer (`center_start`) in the current code. This leads to unstable centering logic, timer resetting on single-frame dropouts, and indefinite hovering. Adding a configurable `grace_s` (grace period) parameter prevents transient jitter from restarting the clock, stabilizing the flight machine's transition.

## Current state

`src/core/ros_px4_template_core/lib/mission/behaviors.py:108-115`:
```python
    err = math.hypot(inputs.pose_enu[0] - tx, inputs.pose_enu[1] - ty)
    centered = err <= tol
    if centered:
        scratch.setdefault("center_start", inputs.now)
    else:
        scratch.pop("center_start", None)
    hold_complete = "center_start" in scratch and inputs.now - scratch["center_start"] >= hold_s
```
If `centered` is `False` for even one frame, the state machine calls `scratch.pop("center_start", None)`, losing all progress.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Run behavior tests | `uv run pytest tests/unit/test_mission_behaviors.py -q` | all pass |
| Full unit suite | `uv run pytest tests/unit/ -q` | all pass |
| Lint | `uv run ruff check src/core/ros_px4_template_core/lib/mission/behaviors.py tests/unit/test_mission_behaviors.py` | exit 0 |
| Typecheck | `uv run ty check src/core/ros_px4_template_core/lib tests/unit` | exit 0 |

## Scope

**In scope**:
- `src/core/ros_px4_template_core/lib/mission/behaviors.py` (modify) — Update `center_on_marker` to support `grace_s` parameter and track grace period in `scratch` before clearing `center_start`.
- `tests/unit/test_mission_behaviors.py` (modify) — Add `test_center_on_marker_grace_period` to verify correct behavior under out-of-bound fluctuations.

**Out of scope**:
- Other mission behaviors in `behaviors.py`.
- `mission_manager.py` or the state transition logic itself.

## Steps

### Step 1: Implement Grace Period in `center_on_marker`

Update the `center_on_marker` implementation to extract `grace_s` (default `1.5` seconds) from `params`. Use `scratch["out_of_bounds_start"]` to record when the drone first went out of bounds. Only clear `center_start` when the elapsed out-of-bounds duration meets or exceeds `grace_s`. Additionally, ensure `hold_complete` is only asserted when the drone is currently `centered`.

Modify `src/core/ros_px4_template_core/lib/mission/behaviors.py:94-118`:
```python
@behavior("center_on_marker")
def center_on_marker(scratch: dict, inputs: Inputs, params: dict) -> BehaviorResult:
    tid = params.get("target_id")
    tid = int(tid) if tid is not None else None
    z = float(params.get("altitude_m", inputs.pose_enu[2]))
    tol = float(params.get("tolerance_m", 0.4))
    hold_s = float(params.get("hold_s", 10.0))
    grace_s = float(params.get("grace_s", 1.5))
    det = _latest(inputs.detections, tid)
    if det is not None:
        tx, ty, _ = marker_world_from_drone(inputs.pose_enu, det.offset_body_flu, inputs.yaw_enu)
        scratch["tx"], scratch["ty"] = tx, ty
    else:
        tx = scratch.get("tx", inputs.pose_enu[0])
        ty = scratch.get("ty", inputs.pose_enu[1])
    err = math.hypot(inputs.pose_enu[0] - tx, inputs.pose_enu[1] - ty)
    centered = err <= tol

    if centered:
        scratch.setdefault("center_start", inputs.now)
        scratch.pop("out_of_bounds_start", None)
    else:
        if "center_start" in scratch:
            if "out_of_bounds_start" not in scratch:
                scratch["out_of_bounds_start"] = inputs.now
            elif inputs.now - scratch["out_of_bounds_start"] >= grace_s:
                scratch.pop("center_start", None)
                scratch.pop("out_of_bounds_start", None)
        else:
            scratch.pop("out_of_bounds_start", None)

    hold_complete = (
        "center_start" in scratch
        and inputs.now - scratch["center_start"] >= hold_s
        and centered
    )
    return BehaviorResult(
        GoTo(tx, ty, z),
        {"centering_error": err, "centered": centered, "hold_complete": hold_complete},
    )
```

**Verify**: `uv run ruff check src/core/ros_px4_template_core/lib/mission/behaviors.py` → exit 0.

### Step 2: Add Behavior Unit Test

Add `test_center_on_marker_grace_period` to `tests/unit/test_mission_behaviors.py` to assert that:
1. Centering starts the timer.
2. An out-of-bounds excursion shorter than the grace period does not clear the timer.
3. Returning to centered within the grace period resets the out-of-bounds timer.
4. An out-of-bounds excursion longer than the grace period successfully clears the timer.

Add the following function to `tests/unit/test_mission_behaviors.py`:
```python
def test_center_on_marker_grace_period() -> None:
    cm = get_behavior("center_on_marker")
    scratch: dict = {}
    det = Detection(id=0, offset_body_flu=(0.0, 0.0, -3.0), stamp=0.0)
    params = {"target_id": 0, "altitude_m": 3.0, "hold_s": 5.0, "tolerance_m": 0.4, "grace_s": 1.5}

    # 1. Centered at t=0.0. Start timer.
    cm(scratch, _inputs(now=0.0, pose_enu=(0.0, 0.0, 3.0), detections=(det,)), params)
    assert "center_start" in scratch
    assert scratch["center_start"] == 0.0

    # 2. Out of bounds at t=2.0 (error 0.5 > tolerance 0.4). Timer should NOT clear.
    r = cm(scratch, _inputs(now=2.0, pose_enu=(0.5, 0.0, 3.0), detections=(det,)), params)
    assert r.signals["centered"] is False
    assert r.signals["hold_complete"] is False
    assert "center_start" in scratch
    assert scratch["out_of_bounds_start"] == 2.0

    # 3. Back in bounds at t=3.0 (elapsed out-of-bounds 1.0s < grace_s 1.5s).
    # out_of_bounds_start is cleared; center_start remains 0.0.
    r = cm(scratch, _inputs(now=3.0, pose_enu=(0.0, 0.0, 3.0), detections=(det,)), params)
    assert r.signals["centered"] is True
    assert "center_start" in scratch
    assert "out_of_bounds_start" not in scratch

    # 4. Out of bounds again at t=4.0.
    r = cm(scratch, _inputs(now=4.0, pose_enu=(0.5, 0.0, 3.0), detections=(det,)), params)
    assert r.signals["centered"] is False
    assert scratch["out_of_bounds_start"] == 4.0

    # 5. Long excursion at t=6.0 (elapsed out-of-bounds 2.0s >= grace_s 1.5s).
    # Both timers must be cleared.
    r = cm(scratch, _inputs(now=6.0, pose_enu=(0.5, 0.0, 3.0), detections=(det,)), params)
    assert "center_start" not in scratch
    assert "out_of_bounds_start" not in scratch
```

**Verify**: `uv run pytest tests/unit/test_mission_behaviors.py -q` → all pass.

### Step 3: Full Verification

Run lint, typechecks, and the full test suite to guarantee no regressions.

```bash
uv run pytest tests/unit/ -q
uv run ruff check src/core/ros_px4_template_core/lib/mission/behaviors.py tests/unit/test_mission_behaviors.py
uv run ty check src/core/ros_px4_template_core/lib tests/unit
```

## Test plan

- Unit tests in `tests/unit/test_mission_behaviors.py` checking the standard dwell completion (`test_center_on_marker_hold_complete_after_dwell`) and the new grace period logic (`test_center_on_marker_grace_period`).
- Run `just check` to verify linting, typechecking, and unit tests.

## Done criteria

- [ ] `src/core/ros_px4_template_core/lib/mission/behaviors.py` is updated to support `grace_s` and keep track of `out_of_bounds_start` to prevent timer reset during short dropouts.
- [ ] `hold_complete` requires `centered` to be `True`.
- [ ] New unit test `test_center_on_marker_grace_period` added to `tests/unit/test_mission_behaviors.py`.
- [ ] `uv run pytest tests/unit/` exits with 0.
- [ ] `uv run ruff check` and `uv run ty check` exit with 0.

## STOP conditions

- If `behaviors.py` does not match the current state (indicating a conflict).
- If the default behavior of `center_on_marker` under well-formed, noise-free scenarios fails (indicating behavior regression).
