# Plan 030: Make the auto_arm disarm latch actually latch (no silent auto-rearm after a disarm)

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report - do not improvise. When done, update the status row for this plan
> in `plans/README.md` - unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat ead4cc6..HEAD -- src/core/ros_px4_template_core/nodes/offboard_controller.py`
> If the file changed since this plan was written, compare the "Current state"
> excerpts against the live code before proceeding; on a mismatch, treat it as
> a STOP condition.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: MED (touches the arming path; live re-verification required)
- **Depends on**: none
- **Category**: bug
- **Planned at**: commit `ead4cc6`, 2026-07-06

## Why this matters

`offboard_controller` intends to stop auto-rearming after the vehicle disarms:
when it observes an armed-to-disarmed transition it sets `self._auto_arm = False`
and logs `AUTO_ARM_DISABLED_ON_DISARM`. But the control loop re-reads the
`auto_arm` ROS parameter every tick and overwrites that latch, so one tick later
auto_arm is back on and the FSM re-commands OFFBOARD and re-arms. In sim this is
masked because scenario cleanup also sets the parameter to false; on hardware
nothing does, so an operator/failsafe disarm (RC kill, landing) can be followed
by an un-commanded rearm and takeoff. The latch must survive parameter re-reads,
while an explicit external `ros2 param set /offboard_controller auto_arm true`
must still re-enable arming (the e2e harness re-arms between scenarios that
share one sim boot - see "Key constraint" below).

## Current state

- `src/core/ros_px4_template_core/nodes/offboard_controller.py` - the only file
  to modify. Single-threaded (`rclpy.spin`), so no locking is needed.

The latch that gets clobbered (`offboard_controller.py:191-197`):

```python
    def _status_cb(self, msg: VehicleStatus) -> None:
        was_armed = self._armed
        self._armed = msg.arming_state == VehicleStatus.ARMING_STATE_ARMED
        self._nav_state = int(msg.nav_state)
        if was_armed and not self._armed:
            self._auto_arm = False
            self.slog.event("AUTO_ARM_DISABLED_ON_DISARM")
```

The clobbering read (`offboard_controller.py:231-232`):

```python
    def _update_state_machine(self) -> None:
        self._auto_arm = bool(self.get_parameter("auto_arm").value)
```

**Key constraint (do not break this):** `tests/scenarios/_common.py` re-enables
arming between scenarios with `ros2 param set /offboard_controller auto_arm true`
(`trigger_auto_arm()`), and `tasks.py` `_run_e2e_sim_group` runs several
scenarios against one sim boot. Scenario N lands and disarms in cleanup;
scenario N+1 must be able to re-arm via that param set. So the latch must be
cleared when the parameter is explicitly set (a fresh external decision), but
must NOT be cleared by the per-tick `get_parameter` re-read of a stale value.

Repo conventions: `StructuredLogger` events via `self.slog.event(...)`
(existing pattern in this file); comments state constraints only.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Quality gate (format, lint, typecheck, build, unit tests) | `just check` | exit 0 |
| Unit tests only (host) | `uv run pytest tests/unit -q` | pass (a pre-existing rclpy collection error in `test_scenario_verdict.py` may appear on hosts without ROS; it is not caused by this plan) |
| Live verification (operator, distrobox) | `just test e2e` | exit 0, all scenarios pass |

## Scope

**In scope** (the only files you should modify):
- `src/core/ros_px4_template_core/nodes/offboard_controller.py`

**Out of scope** (do NOT touch, even though they look related):
- `src/core/ros_px4_template_core/lib/offboard_fsm.py` - the pure FSM already
  honors `auto_arm=False`; the bug is in how the node computes that input.
- `tests/scenarios/_common.py` - its param-set re-arm flow is the contract this
  plan must keep working.
- `config/params/*.yaml` - no default changes.

## Git workflow

- Branch: `advisor/030-auto-arm-disarm-latch`
- Commit style: conventional commits, e.g. `fix(offboard): latch auto_arm off after disarm until param is re-set`
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Add the persistent latch

In `OffboardController.__init__` (near the other state fields around line 87),
add:

```python
        self._disarm_latched = False
```

In `_status_cb`, replace the `self._auto_arm = False` line with latch setting
(keep the event log):

```python
        if was_armed and not self._armed:
            self._disarm_latched = True
            self.slog.event("AUTO_ARM_DISABLED_ON_DISARM")
```

**Verify**: `uv run ruff check src/core/ros_px4_template_core/nodes/offboard_controller.py` -> exit 0

### Step 2: Honor the latch in the per-tick param read

In `_update_state_machine`, change the first line to:

```python
        self._auto_arm = bool(self.get_parameter("auto_arm").value) and not self._disarm_latched
```

**Verify**: `uv run ruff check src/core/ros_px4_template_core/nodes/offboard_controller.py` -> exit 0

### Step 3: Clear the latch on an explicit external param set

Register a set-parameters callback in `__init__` (after the parameters are
declared, before the subscriptions), so that an explicit
`ros2 param set /offboard_controller auto_arm true` is treated as a fresh
arming decision:

```python
        from rcl_interfaces.msg import SetParametersResult

        def _on_set_params(params) -> SetParametersResult:
            for p in params:
                if p.name == "auto_arm" and bool(p.value):
                    if self._disarm_latched:
                        self._disarm_latched = False
                        self.slog.event("AUTO_ARM_LATCH_CLEARED_BY_PARAM")
            return SetParametersResult(successful=True)

        self.add_on_set_parameters_callback(_on_set_params)
```

Put the import at the top of the file with the other `rcl_interfaces`-style
imports (there are none today; place it after the `px4_msgs` import block).
Note: `declare_parameter` calls made before registration do not fire this
callback, so launch-time overlay values (e.g. `auto_arm: true` from
`config/params/overlays/auto_arm.yaml`) do not touch the latch - correct,
since no disarm has happened yet at that point.

**Verify**: `just check` -> exit 0

### Step 4: Live verification (operator sign-off)

This is behavior on the arming path; unit tests cannot cover the rclpy node.
Run, in the distrobox / a ROS-capable shell:

1. `just test e2e` -> exit 0. This exercises the exact multi-scenario
   land-disarm-then-rearm flow the latch must not break (scenario cleanup
   disarms, next scenario re-arms via `ros2 param set`).
2. Manual latch check: `just sim --overlay auto_arm`, wait for takeoff
   (`just log tail`), then `ros2 topic pub --once /fmu/in/vehicle_command px4_msgs/msg/VehicleCommand "{command: 21, target_system: 1, target_component: 1, source_system: 1, source_component: 1, from_external: true}"`
   (NAV_LAND). After landing and disarm, confirm in `logs/latest.log`:
   `rg AUTO_ARM_DISABLED_ON_DISARM logs/latest.log` -> one event, and no
   subsequent `ARM_COMMAND_SENT` events after it
   (`rg ARM_COMMAND_SENT logs/latest.log` shows none with a later `t=`).
3. `just stop`.

If you cannot run a sim in your environment, complete steps 1-3 of the plan,
run `just check`, then STOP and report that live verification is pending
operator sign-off (this matches how plans 005/006/020 were handled).

## Test plan

No new unit tests: the changed logic lives in the rclpy node, and this repo
deliberately keeps node classes out of the unit suite (pure logic goes to
`lib/`, see `lib/offboard_fsm.py` + `tests/unit/test_offboard_fsm.py`). The
FSM's handling of `auto_arm=False` is already covered there. Verification is
`just check` plus the live e2e run above.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `just check` exits 0
- [ ] `rg -n "_disarm_latched" src/core/ros_px4_template_core/nodes/offboard_controller.py` shows the field set in `_status_cb`, read in `_update_state_machine`, and cleared in the set-parameters callback
- [ ] `rg -n "self._auto_arm = False" src/core/ros_px4_template_core/nodes/offboard_controller.py` returns no matches (the direct clobbered write is gone)
- [ ] `git status` shows no files outside the in-scope list modified
- [ ] Live: `just test e2e` exits 0 (or the plan is reported back as pending operator sign-off)
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- The excerpts above do not match the live code (drift).
- `just test e2e` fails on a scenario that passes on `main` without this change
  (the latch broke the shared-sim re-arm flow; the param-callback clearing is
  not working).
- You find another writer of `self._auto_arm` besides the three sites named
  here (`__init__` line 74, `_status_cb`, `_update_state_machine`).

## Maintenance notes

- Plan 042 (precision landing) builds on this latch concept: a commanded land
  will set the same kind of internal no-rearm state. Reviewers of 042 should
  check it composes with `_disarm_latched`.
- Reviewer should scrutinize: the parameter callback must return
  `SetParametersResult(successful=True)` unconditionally, or unrelated param
  sets will start failing.
- Deferred: exposing the latch state in `ControllerStatus` (would need a msg
  change); the `AUTO_ARM_LATCH_CLEARED_BY_PARAM` event is the observable for now.
