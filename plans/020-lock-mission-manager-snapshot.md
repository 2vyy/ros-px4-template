# Plan 020: `mission_manager` builds its input snapshot from consistent state

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving on. If
> anything in "STOP conditions" occurs, stop and report — do not improvise. When
> done, update this plan's row in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 0f93f0e..HEAD -- src/core/ros_px4_template_core/nodes/mission_manager.py`
> If it changed, compare the "Current state" excerpts to the live code before
> proceeding; on a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: MED
- **Depends on**: none
- **Category**: correctness
- **Planned at**: commit `0f93f0e`, 2026-06-22

## Why this matters

`docs/MISSIONS.md:52-55` promises the engine reads an **immutable per-tick
`Inputs` snapshot** so "a value cannot change underneath them mid-tick — this is
what keeps transitions race-free." That guarantee holds *once the snapshot is
built*, but the **construction itself** reads node fields that subscription
callbacks mutate concurrently. `mission_manager` runs a `MultiThreadedExecutor`
with subscriptions in a `ReentrantCallbackGroup`, so `_detection_cb` / `_odom_cb`
/ `_controller_cb` can run on other threads while `_tick` → `_snapshot` reads
their fields. The realest hazards: the marker null-check then tuple-build
(`_marker_offset_body` can be set to `None` between the check and the read), and
the stability counter (`_snapshot` writes `self._marker_stability = 0` while
`_detection_cb` does `+= 1`). The result is a torn snapshot — a transient that
can mis-fire a vision guard. Building the snapshot under a lock makes the
documented "race-free" guarantee actually true. MED risk because it touches the
node's hot path; mitigated by holding the lock only around field reads/writes,
never around the engine tick or any publish.

## Current state

`src/core/ros_px4_template_core/nodes/mission_manager.py`:

- Executor + callback groups (`__init__`, lines 53-54, and `main`, line 236):
  ```python
  self._tick_group = MutuallyExclusiveCallbackGroup()
  self._sub_group = ReentrantCallbackGroup()
  ...
  executor = MultiThreadedExecutor()
  ```
  Subscriptions use `callback_group=self._sub_group` (lines 91, 94, 101); the
  tick timer uses `self._tick_group` (line 113).

- The mutated fields, written by callbacks (lines 116-140):
  ```python
  def _controller_cb(self, msg):   # writes self._armed, self._ctrl_alt
  def _odom_cb(self, msg):         # writes self._pos_enu, self._yaw_enu, self._have_odom, self._odom_time
  def _detection_cb(self, msg):    # writes self._marker_offset_body, self._marker_id_seen,
                                   #        self._marker_time, self._marker_stability (+=1 or reset 0)
  ```

- The snapshot read, in the tick thread (lines 142-168):
  ```python
  def _snapshot(self, now: float) -> Inputs:
      dets: tuple[Detection, ...] = ()
      stability: dict[int, int] = {}
      if self._marker_offset_body is not None and now - self._marker_time <= 1.0:
          dets = (Detection(id=self._marker_id_seen,
                            offset_body_flu=self._marker_offset_body,
                            stamp=self._marker_time),)
          if now - self._marker_time <= _STABLE_FRESH_S:
              stability = {self._marker_id_seen: self._marker_stability}
      else:
          self._marker_stability = 0
      z_eff = max(self._pos_enu[2], self._ctrl_alt)
      return Inputs(now=now,
                    pose_enu=(self._pos_enu[0], self._pos_enu[1], z_eff),
                    yaw_enu=self._yaw_enu, armed=self._armed,
                    altitude_ok=z_eff >= self._takeoff_alt - self._takeoff_alt_tol,
                    estimate_ok=self._estimate_ok, detections=dets,
                    detection_stability=stability,
                    input_ages={"odom": (now - self._odom_time) if self._have_odom else float("inf")})
  ```

There is **no** lock today. `_tick` calls `_snapshot(now)` (line 175).

This node is exercised only by live scenarios (01/02/03/05/06); there is no unit
test for `mission_manager` because it is a ROS node (needs an rclpy graph). The
change is therefore verified by reasoning + lint/typecheck + an unchanged live
scenario run, not by a new unit test (see Test plan).

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Lint the node | `uv run ruff check src/core/ros_px4_template_core/nodes/mission_manager.py` | exit 0 |
| Typecheck lib (node not in ty paths) | `uv run ty check src/core/ros_px4_template_core/lib tests/unit tools/` | exit 0 |
| Full unit suite (no regressions) | `uv run pytest tests/unit/ -q` | all pass |
| Live re-verify (operator/distrobox) | `just scenario 05_aruco_hover` then `just scenario 03_waypoint` | both PASS |

Note: `mission_manager.py` is **not** in the `ruff`/`ty` path set of `just
check` (`tasks.py:392,422`), so run the explicit `ruff check` on the file above.
The live scenario re-verification needs Gazebo/PX4 (distrobox `ubuntu`); if you
cannot run it, finish the code + lint and hand the live sign-off to the operator
(see STOP conditions).

## Scope

**In scope**:
- `src/core/ros_px4_template_core/nodes/mission_manager.py` only.

**Out of scope** (do NOT touch):
- `lib/mission/engine.py`, `types.py`, `loader.py` — the engine and `Inputs` are
  fine; the bug is in how the node *fills* `Inputs`.
- The callback-group / executor choice — keep `MultiThreadedExecutor` +
  `ReentrantCallbackGroup`; do not serialize everything onto one thread (that
  changes latency characteristics). The lock is the targeted fix.
- Publishing (`_publish_target`/`_publish_status`/`_publish_markers`) — do not
  hold the lock across publishes.
- `marker_localizer.py` and the other nodes.

## Git workflow

- Branch: `advisor/020-lock-mission-manager-snapshot`
- Conventional commit (e.g.
  `fix(mission_manager): build the input snapshot under a lock so it is consistent`).
- Do NOT push or open a PR unless instructed.

## Steps

### Step 1: Add a lock and guard every shared-field access

In `__init__`, add `import threading` at the top of the file (with the other
stdlib imports, after `import math`) and create the lock alongside the callback
groups:
```python
self._state_lock = threading.Lock()
```

Wrap **the body of each subscription callback** that writes shared fields, and
**the field reads/writes inside `_snapshot`**, with `self._state_lock`. Keep the
critical sections minimal — only the attribute reads/writes, never the engine
`tick`, never a publish, never logging.

- `_controller_cb`: hold the lock around the two assignments.
- `_odom_cb`: hold the lock around the five assignments (`_pos_enu`, `_yaw_enu`,
  `_have_odom`, `_odom_time`). Compute `enu_yaw_from_quaternion(...)` *before*
  taking the lock if you prefer to keep the lock tiny.
- `_detection_cb`: hold the lock around the whole mutate block (the `if not
  msg.valid` reset path and the increment path).
- `_snapshot`: take the lock once, copy the shared fields into **locals**
  (`pos = self._pos_enu`, `ctrl_alt = self._ctrl_alt`, `armed = self._armed`,
  `yaw = self._yaw_enu`, `have_odom = self._have_odom`, `odom_time =
  self._odom_time`, `marker_offset = self._marker_offset_body`, `marker_id =
  self._marker_id_seen`, `marker_time = self._marker_time`, `marker_stab =
  self._marker_stability`), apply the `else: self._marker_stability = 0` reset
  **while still holding the lock**, then **release the lock** and build the
  `Inputs` from the locals. The `Inputs` construction and the `max(...)` /
  freshness arithmetic happen on the locals, lock-free.

The net effect: every read in `_snapshot` sees a single consistent generation of
the fields, and the stability reset no longer races the increment.

**Verify**: `uv run ruff check src/core/ros_px4_template_core/nodes/mission_manager.py`
→ exit 0. Visually confirm no `self._pub_*.publish(...)` or `tick(...)` call sits
inside a `with self._state_lock:` block.

### Step 2: Confirm no lock is held across blocking work

Re-read `_tick` (lines 170-188): `tick(self._ctx, self._mission, inputs)` and all
`_publish_*` calls must be **outside** any `with self._state_lock:` block.
`_snapshot` returns a fully-built `Inputs` (no shared-field access after it
returns), so `_tick` never needs the lock itself.

**Verify**: `grep -n "with self._state_lock" src/core/ros_px4_template_core/nodes/mission_manager.py`
→ matches appear only inside the callbacks and `_snapshot`, never in `_tick`.

## Test plan

- No new unit test is added (the node requires a live rclpy graph; `lib/` holds
  the unit-tested pure logic and is unchanged). State this in the PR.
- The behavioral guarantee is verified by **re-running the existing live
  scenarios unchanged**, on the operator's sim:
  - `just scenario 03_waypoint` → PASS (path-following unaffected)
  - `just scenario 05_aruco_hover` → PASS (the marker/stability path that this
    change protects)
  - `just scenario 06_search_relocalize` → PASS (uses `marker_stable` guard)
- These must PASS exactly as before; the change is correctness-preserving, not
  behavior-changing.

## Done criteria

ALL must hold:

- [ ] `uv run ruff check src/core/ros_px4_template_core/nodes/mission_manager.py` exits 0
- [ ] `uv run ty check src/core/ros_px4_template_core/lib tests/unit tools/` exits 0
- [ ] `uv run pytest tests/unit/ -q` exits 0 (no regressions)
- [ ] `grep -n "with self._state_lock" mission_manager.py` shows the lock used in all 3 callbacks and `_snapshot`, and NOT in `_tick`
- [ ] No `publish(...)` or `tick(...)` call is inside a `with self._state_lock:` block
- [ ] (Operator/distrobox) `just scenario 03_waypoint`, `05_aruco_hover`, `06_search_relocalize` all PASS
- [ ] Only `mission_manager.py` is modified
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report if:

- `mission_manager.py` lines 53-54, 116-168, or 236 do not match "Current state"
  (the node drifted — especially if the callback groups or executor changed; a
  single-threaded executor would make this plan unnecessary).
- A live scenario that PASSed before now FAILs or hangs after the change — that
  signals the lock is held too long (across `tick`/publish) and is starving
  callbacks; revert and report rather than widening the critical section.
- You cannot run any live scenario (no sim/distrobox). Finish the code + lint +
  typecheck, mark the live re-verification as pending operator sign-off, and STOP
  — do NOT mark the plan DONE without the scenario evidence.

## Maintenance notes

- If a future change moves the executor to single-threaded or the subscriptions
  to a `MutuallyExclusiveCallbackGroup` shared with the tick, the lock becomes
  redundant (but harmless) — leave a comment so a future maintainer knows why it
  exists.
- Reviewer: scrutinize the lock scope — the whole point is a *small* critical
  section. Any `tick`/publish/log inside the lock is a defect.
- Follow-up deliberately deferred: a stricter "N consecutive fresh frames"
  definition of marker stability (a separate behavior-change discussion); this
  plan only makes the existing semantics race-free, it does not redefine them.
