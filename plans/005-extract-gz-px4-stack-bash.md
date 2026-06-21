# Plan 005: Extract the gz/PX4 boot bash blob to sim/launch/_start_gz_px4.sh

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat 21cbe3d..HEAD -- sim/launch/sim_full.launch.py`
> If `sim_full.launch.py` changed since this plan was written, compare the
> "Current state" excerpts against the live file before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P3
- **Effort**: M
- **Risk**: MED
- **Depends on**: none
- **Category**: tech-debt
- **Planned at**: commit `21cbe3d`, 2026-06-21

## Why this matters

`sim/launch/sim_full.launch.py` builds the PX4/Gazebo boot command as one ~90
line Python-interpolated bash string inside `_gz_px4_stack`
(`sim_full.launch.py:101-189`). That blob embeds hard-won, load-bearing
knowledge: the exact env exports, and *why* `PX4_SIM_SPEED_FACTOR` must not be
exported at speed 1.0 (it zeroes the physics step and causes an altitude
runaway). Buried in an f-string it is hard to read, hard to shellcheck, and
easy to break with a stray quote. Moving it to a real `_start_gz_px4.sh` makes
the boot sequence a readable, lintable script and shrinks the launch file to
path-computation. **Behavior must not change** — the same env, same command,
same lockstep boot.

## Current state

`_gz_px4_stack(context, ...)` (`sim_full.launch.py:101-189`) does two things:

1. Computes paths from helpers already in the file:
   - `_require_px4_dir()` (`:24`), `_world_sdf(project_root, px4_dir, world)`
     (`:39`) returns `(_world_sdf_path, px4_gz_worlds)`, `_gz_paths(...)`
     (`:47`), `_px4_build(px4_dir)` (`:61`).
   - plus `plugins = f"{build}/src/modules/simulation/gz_plugins"` and
     `server_config = f"{px4_dir}/Tools/simulation/gz/server.config"`.
   - reads `world`, `model`, `headless`, `speed` from `LaunchConfiguration`,
     and caps `speed` to 1.0 if `<= 0 or > 1.0` (prints a warning).
2. Builds a bash string (`common_env` + conditional `speed_export` /
   `headless_export` + `cd build` + `rm -f rootfs/parameters*.bson` +
   `exec env PX4_GZ_WORLD=.. PX4_SIM_MODEL=gz_.. ./bin/px4`) and returns
   `[ExecuteProcess(cmd=["bash", "-c", cmd], name="gz_px4_stack", output="screen")]`.

The exact current body (lines 115-189), reproduce its semantics precisely:

```python
    world = LaunchConfiguration("world").perform(context)
    model = LaunchConfiguration("model").perform(context)
    headless = LaunchConfiguration("headless").perform(context).lower() == "true"
    speed = float(LaunchConfiguration("speed").perform(context))
    if speed <= 0 or speed > 1.0:
        print(f"[sim_full] WARNING: speed factor {speed} is invalid, capping to 1.0", flush=True)
        speed = 1.0

    project_root = Path(__file__).resolve().parents[2]
    px4_dir = _require_px4_dir()
    build = _px4_build(px4_dir)
    _world_sdf_path, px4_gz_worlds = _world_sdf(project_root, px4_dir, world)
    gz_paths = _gz_paths(project_root, px4_dir)
    plugins = f"{build}/src/modules/simulation/gz_plugins"
    server_config = f"{px4_dir}/Tools/simulation/gz/server.config"

    speed_export = f"export PX4_SIM_SPEED_FACTOR={speed}; " if speed != 1.0 else ""
    common_env = ( ... long string of exports ... )   # lines 140-161
    headless_export = "export HEADLESS=1; " if headless else ""
    cmd = ( common_env + headless_export + f'cd "{build}"; '
        "rm -f rootfs/parameters*.bson 2>/dev/null; "
        + f'exec env PX4_GZ_WORLD="{world}" PX4_SIM_MODEL=gz_{model} ./bin/px4' )
    return [ExecuteProcess(cmd=["bash", "-c", cmd], name="gz_px4_stack", output="screen")]
```

The full set of exports in `common_env` (lines 140-161), which move verbatim
(as comments + `export` lines) into the script:
`GZ_IP=127.0.0.1`, the conditional `PX4_SIM_SPEED_FACTOR`,
`GZ_SIM_RESOURCE_PATH={gz_paths}`, `PX4_GZ_WORLDS={px4_gz_worlds}`,
`PX4_GZ_PLUGINS={plugins}`, `PX4_GZ_SERVER_CONFIG={server_config}`,
`GZ_SIM_SERVER_CONFIG_PATH={server_config}`,
`GZ_SIM_SYSTEM_PLUGIN_PATH={plugins}`,
`LD_LIBRARY_PATH={plugins}:${LD_LIBRARY_PATH}`,
`PX4_PARAM_COM_ARM_WO_GPS=1`, `PX4_PARAM_CBRK_SUPPLY_CHK=894281`,
`PX4_PARAM_COM_SPOOLUP_TIME=0.0`, `PX4_PARAM_EKF2_GPS_CHECK=0`,
`PX4_PARAM_EKF2_GPS_CTRL=7`, plus the `set -e` at the top and the two big
explanatory comments (the `PX4_SIM_SPEED_FACTOR` hazard and the "do NOT override
SIM_GZ_EC_MIN / MPC_THR" note). **These comments are the reason this code is
correct — preserve their text.**

Invocation context: `_gz_px4_stack` is wired as
`OpaqueFunction(function=_gz_px4_stack)` in `generate_launch_description`
(`sim_full.launch.py:260`). That wiring does not change.

Convention: other boot steps in this file are also `ExecuteProcess(cmd=["bash",
"-c", ...])` (e.g. `_clock_bridge:93`, `agent_action:231`). This plan is the
first to use a standalone `.sh`; that is intentional for the largest blob.
`additional_env` on `ExecuteProcess` (a launch API) is how the computed paths
reach the script.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Quality gate (lint+typecheck) | `just check` | exits 0, `all checks passed.` |
| Shell lint (if installed) | `shellcheck sim/launch/_start_gz_px4.sh` | exits 0 (or "command not found" — then skip) |
| Confirm blob left the .py | `rg -n "PX4_PARAM_EKF2_GPS_CTRL\|MPC_THR_HOVER" sim/launch/sim_full.launch.py` | no matches |
| Confirm knowledge moved to .sh | `rg -n "altitude .runaway.\|EKF2_GPS_CTRL\|stock thrust" sim/launch/_start_gz_px4.sh` | matches present |
| Sim boot (DECISIVE — needs full env) | `just sim` then `just scenario 01_arm_takeoff` then `just stop` | `READY`, then scenario `PASS`, clean stop |

## Scope

**In scope**:
- `sim/launch/_start_gz_px4.sh` (create)
- `sim/launch/sim_full.launch.py` (rewrite `_gz_px4_stack` body only)
- `plans/README.md` (status row only — skip if a reviewer owns the index)

**Out of scope** (do NOT touch):
- Any other function in `sim_full.launch.py` (`_clock_bridge`, `_vision_bridge`,
  `_pose_setup`, `agent_action`, `generate_launch_description`, the path
  helpers). Only `_gz_px4_stack`'s body changes; its name, signature, and the
  `OpaqueFunction` wiring stay identical.
- `hardware/launch/hardware.launch.py`, any node, any config. This is a launch
  refactor with zero behavior change.
- The env values themselves. Do not add, drop, reorder for "cleanliness", or
  re-tune any `export`. Byte-for-byte the same exports, same conditional logic.

## Git workflow

- Branch: `advisor/005-extract-gz-px4-stack-bash`
- Commit style: conventional commits. Suggested message:
  `refactor(sim): extract gz/px4 boot bash to _start_gz_px4.sh`.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Create `sim/launch/_start_gz_px4.sh`

Create the file with exactly this content (it carries every export and comment
from `common_env`, with the conditional speed/headless logic moved into bash):

```bash
#!/usr/bin/env bash
# Start PX4 SITL (non-standalone); PX4's own rcS starts Gazebo and spawns the model.
#
# Invoked by sim/launch/sim_full.launch.py (_gz_px4_stack), which computes the
# paths and passes them as the environment variables this script reads:
#   PX4_BUILD          px4_sitl_default build dir (cd target; holds ./bin/px4)
#   GZ_PATHS           colon-joined GZ_SIM_RESOURCE_PATH
#   PX4_GZ_WORLDS_DIR  dir holding <world>.sdf (our sim/worlds or PX4's)
#   PX4_GZ_PLUGINS_DIR gz_plugins build dir
#   PX4_GZ_SERVER_CFG  PX4 gz server.config path
#   SIM_WORLD SIM_MODEL  world and model names
#   SIM_SPEED          real-time speed factor as a string (e.g. 1.0)
#   HEADLESS_FLAG      "1" for headless, else empty
#
# We do NOT pre-start `gz sim`. PX4 runs WITHOUT PX4_GZ_STANDALONE, so its rcS
# starts Gazebo late in boot via ${PX4_GZ_WORLDS}/${world}.sdf and immediately
# attaches gz_bridge, giving a clean lockstep boot. Pre-starting gz ourselves let
# it free-run ~7-9 s before PX4 attached, corrupting IMU/baro timing to EKF2
# divergence to a phantom altitude runaway. Flight uses stock thrust calibration
# (no SIM_GZ_EC_MIN / MPC_THR overrides), verified to hold altitude.
set -e

export GZ_IP=127.0.0.1

# CRITICAL: only export PX4_SIM_SPEED_FACTOR for non-realtime runs. Setting it at
# all makes PX4's rcS (px4-rc.gzsim) call the gz set_physics service, which sends
# real_time_factor but leaves max_step_size unset, so protobuf defaults it to 0,
# overwriting the world's 0.004 step. The zero step makes physics integration blow
# up: after arming the vehicle climbs away uncontrollably (the altitude "runaway").
# At the default speed=1.0 we omit it and the world's own real-time settings apply.
# (verified: omitting it gives a clean 3 m offboard hold.)
if [ "$SIM_SPEED" != "1.0" ]; then
  export PX4_SIM_SPEED_FACTOR="$SIM_SPEED"
fi

export GZ_SIM_RESOURCE_PATH="$GZ_PATHS"
export PX4_GZ_WORLDS="$PX4_GZ_WORLDS_DIR"
export PX4_GZ_PLUGINS="$PX4_GZ_PLUGINS_DIR"
export PX4_GZ_SERVER_CONFIG="$PX4_GZ_SERVER_CFG"
export GZ_SIM_SERVER_CONFIG_PATH="$PX4_GZ_SERVER_CFG"
export GZ_SIM_SYSTEM_PLUGIN_PATH="$PX4_GZ_PLUGINS_DIR"
export LD_LIBRARY_PATH="$PX4_GZ_PLUGINS_DIR:${LD_LIBRARY_PATH}"

# Applied at STARTUP (reliable) rather than via gcs_heartbeat over lossy UDP.
# Arming/EKF reliability: allow GPS fusion without strict SITL checks, arm w/o GPS.
export PX4_PARAM_COM_ARM_WO_GPS=1
export PX4_PARAM_CBRK_SUPPLY_CHK=894281
export PX4_PARAM_COM_SPOOLUP_TIME=0.0
export PX4_PARAM_EKF2_GPS_CHECK=0
export PX4_PARAM_EKF2_GPS_CTRL=7
# NOTE: do NOT override SIM_GZ_EC_MIN / MPC_THR_HOVER / MPC_THR_MIN here.
# Stock x500 airframe defaults (EC_MIN=150, MPC_THR_HOVER=0.60) produce stable
# offboard altitude hold, verified against bare PX4 SITL. The earlier overrides
# (EC_MIN=0, MPC_THR_HOVER=0.15) came from a debunked "idle approx hover" theory
# and actually broke flight (no liftoff / runaway). Keep stock thrust calibration.

if [ "$HEADLESS_FLAG" = "1" ]; then
  export HEADLESS=1
fi

echo "[sim_full] Starting PX4 (it starts Gazebo in lockstep) world='$SIM_WORLD' model='$SIM_MODEL'"

cd "$PX4_BUILD"
# Boot from stock airframe defaults every time (determinism): clear any params
# persisted by a prior run so flight behaviour never drifts between launches.
rm -f rootfs/parameters*.bson 2>/dev/null || true
exec env PX4_GZ_WORLD="$SIM_WORLD" PX4_SIM_MODEL="gz_${SIM_MODEL}" ./bin/px4
```

**Verify**: `rg -n "EKF2_GPS_CTRL" sim/launch/_start_gz_px4.sh` matches; if
`shellcheck` is installed, `shellcheck sim/launch/_start_gz_px4.sh` exits 0.

### Step 2: Rewrite the body of `_gz_px4_stack` to call the script

Replace the body from `speed_export = ...` (line 138) through the `return [...]`
(line 189) so the function keeps its path computation (lines 115-129 unchanged)
and ends with:

```python
    script = Path(__file__).resolve().parent / "_start_gz_px4.sh"
    return [
        ExecuteProcess(
            cmd=["bash", str(script)],
            additional_env={
                "PX4_BUILD": build,
                "GZ_PATHS": gz_paths,
                "PX4_GZ_WORLDS_DIR": px4_gz_worlds,
                "PX4_GZ_PLUGINS_DIR": plugins,
                "PX4_GZ_SERVER_CFG": server_config,
                "SIM_WORLD": world,
                "SIM_MODEL": model,
                "SIM_SPEED": f"{speed}",
                "HEADLESS_FLAG": "1" if headless else "",
            },
            name="gz_px4_stack",
            output="screen",
        )
    ]
```

Keep the function's docstring but trim it to one line that points at the script
for the boot rationale (the detailed comments now live in the `.sh`). Leave the
`speed` cap/validation (lines 118-121) and all path computation in place. Do not
change the `OpaqueFunction(function=_gz_px4_stack)` wiring.

**Verify**: `rg -n "PX4_PARAM_EKF2_GPS_CTRL|MPC_THR_HOVER|common_env|speed_export" sim/launch/sim_full.launch.py` returns no matches (the blob is gone from the `.py`).

### Step 3: Run the quality gate

**Verify**: `just check` exits 0 and ends with `all checks passed.` (lint +
typecheck cover `sim/launch/sim_full.launch.py`).

### Step 4: Sim boot verification (DECISIVE)

This refactor's correctness is only proven by a real boot: the script must
produce the same lockstep start and stable altitude hold. Run:

```
just sim
just scenario 01_arm_takeoff
just stop
```

**Verify**: `just sim` prints `READY`; the scenario prints `PASS`; `just stop`
leaves no process. A `FAIL` or an altitude runaway means the env/script diverged
from the original.

If you CANNOT run the sim in this environment (no `PX4_DIR`, not Linux with
Gazebo, or `just sim` reports `NOT READY` for environment reasons unrelated to
this change), do NOT mark the plan done: complete Steps 1-3, then STOP and report
"sim verification pending — operator must run Step 4" (see STOP conditions).

## Test plan

No unit tests (launch glue is not unit-tested in this repo). Verification is:
- Static: Steps 1-3 greps + `just check` + optional `shellcheck`.
- Dynamic (decisive): Step 4 `just scenario 01_arm_takeoff` PASS, which
  exercises the exact boot path this plan refactors (arm + 3 m offboard hold,
  the same check that originally caught the `PX4_SIM_SPEED_FACTOR` runaway).

## Done criteria

ALL must hold:

- [ ] `sim/launch/_start_gz_px4.sh` exists and carries the two CRITICAL comments
- [ ] `rg -n "common_env|speed_export|EKF2_GPS_CTRL" sim/launch/sim_full.launch.py` returns no matches
- [ ] `just check` exits 0
- [ ] `just scenario 01_arm_takeoff` prints `PASS` (or the plan is reported as "sim verification pending" per STOP conditions, NOT marked done)
- [ ] No files outside the in-scope list are modified (`git status`)
- [ ] `plans/README.md` status row for 005 updated (unless a reviewer owns the index)

## STOP conditions

Stop and report back (do not improvise) if:

- The excerpts in "Current state" no longer match `sim_full.launch.py`.
- `just check` fails for a reason traceable to the edit (syntax, import).
- `just scenario 01_arm_takeoff` FAILs or shows an altitude runaway — the env
  set diverged; report the diff between the script's exports and the original
  `common_env` rather than guessing.
- You cannot run `just sim` at all (missing `PX4_DIR`, non-Linux, no Gazebo).
  Finish Steps 1-3, report STATUS with Step 4 explicitly marked "pending operator
  sim verification". A launch refactor that has not booted is not "done".

## Maintenance notes

- The boot knowledge now lives in `_start_gz_px4.sh`. Future env tweaks
  (PX4 version bumps, new EKF params) edit the script, not the launch file.
- A reviewer should diff the script's `export` lines against the pre-refactor
  `common_env` block (git history at `21cbe3d`) and confirm they match exactly,
  and confirm the `SIM_SPEED != "1.0"` guard preserves the "omit at default
  speed" rule that prevents the physics runaway.
- If a second airframe/world ever needs different boot env, parameterize via new
  env vars passed from `additional_env`, keeping the single script.
