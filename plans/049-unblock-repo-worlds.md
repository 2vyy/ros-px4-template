# Plan 049: Repo-only Gazebo worlds boot via `just sim --world <w>` (unblock plan 043)

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 01f94c7..HEAD -- sim/launch/ tools/wait_ready.py tasks.py docs/SIM.md`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.
>
> **This plan needs a live sim environment** (PX4_DIR checkout + Gazebo, i.e.
> the `ubuntu` distrobox or a native Jazzy host). If you cannot run
> `just sim`, STOP immediately and report.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MED (boot-handoff timing; the repo has been burned here before — read "Why the obvious fixes fail" below)
- **Depends on**: none (unblocks the BLOCKED plan 043 and is a prerequisite for plan 062)
- **Category**: bug
- **Planned at**: commit `01f94c7`, 2026-07-10

## Why this matters

Plan 043 shipped three competition practice worlds (`sim/worlds/marker_field.sdf`,
`landing_pad.sdf`, `obstacle_course.sdf`) that validate with `gz sdf -k` but
**cannot boot**: `just sim --world marker_field` ends NOT READY. The blocker is
inside PX4's own boot scripts (which we must never edit — repo invariant #3:
never modify files under `PX4_DIR`). Until this lands, every competition-world
capability (GUI practice, and later real-camera perception scenarios, plan 062)
is dead on arrival.

## Current state — root cause, verified line by line

`PX4_DIR` is defined in `.env` (currently `/home/ivy/robotics/PX4-Autopilot`).
Read it from `.env`, never hardcode it.

1. Our launch resolves a repo world and exports the right dirs.
   `sim/launch/sim_full.launch.py:39-44`:

   ```python
   def _world_sdf(project_root: Path, px4_dir: str, world: str) -> tuple[str, str]:
       sim_worlds = project_root / "sim" / "worlds"
       px4_worlds = Path(px4_dir) / "Tools" / "simulation" / "gz" / "worlds"
       if (sim_worlds / f"{world}.sdf").exists():
           return str(sim_worlds / f"{world}.sdf"), str(sim_worlds)
       return str(px4_worlds / f"{world}.sdf"), str(px4_worlds)
   ```

   `sim/launch/_start_gz_px4.sh` exports `PX4_GZ_WORLDS="$PX4_GZ_WORLDS_DIR"`,
   then `cd "$PX4_BUILD"` and
   `exec env PX4_GZ_WORLD="$SIM_WORLD" PX4_SIM_MODEL="gz_${SIM_MODEL}" ./bin/px4`.

2. PX4's rcS destroys the exported dir. `<PX4_DIR>/build/px4_sitl_default/rootfs/gz_env.sh`
   (generated; read-only for us):

   ```bash
   export PX4_GZ_WORLDS=<PX4_DIR>/Tools/simulation/gz/worlds   # unconditional clobber
   export GZ_SIM_RESOURCE_PATH=$GZ_SIM_RESOURCE_PATH:$PX4_GZ_MODELS:$PX4_GZ_WORLDS  # appends (ours survives)
   ```

3. `<PX4_DIR>/ROMFS/px4fmu_common/init.d-posix/px4-rc.gzsim` (read-only), the
   non-standalone branch:

   ```bash
   if [ -z "${PX4_GZ_STANDALONE}" ]; then
       # Look for an already running world
       gz_world=$( ${gz_command} topic -l | grep -m 1 -e "^/world/.*/clock" | sed 's/\/world\///g; s/\/clock//g' )
       if [ -z "${gz_world}" ] && [ -n "${PX4_GZ_WORLD}" ]; then
           if [ -f ./gz_env.sh ]; then . ./gz_env.sh          # <- clobber happens HERE
           elif [ -f ../gz_env.sh ]; then . ../gz_env.sh; fi
           ${gz_command} ${gz_sub_command} --verbose=${GZ_VERBOSE:=1} -r -s "${PX4_GZ_WORLDS}/${PX4_GZ_WORLD}.sdf" &
       else
           echo "INFO  [init] gazebo already running world: ${gz_world}"
           PX4_GZ_WORLD=${gz_world}                           # <- adopts the running world, NO gz_env.sh source
       fi
   fi
   # later: waits on service /world/${PX4_GZ_WORLD}/scene/info (30 x 1s), then spawns the model + gz_bridge
   ```

So for repo worlds PX4 tries to open
`<PX4_DIR>/Tools/simulation/gz/worlds/marker_field.sdf`, which does not exist,
and the boot times out. `default` works because PX4 ships its own `default.sdf`.

### Why the obvious fixes fail (do NOT retry these)

- **Symlink/copy the world into PX4's worlds dir** — writes under `PX4_DIR`,
  violates invariant #3. Rejected.
- **Relative-traversal world name** (`PX4_GZ_WORLD="../../../…/marker_field"`):
  the file load would resolve, but `PX4_GZ_WORLD` is *also* used as the world
  NAME in `check_scene_info` (`/world/${PX4_GZ_WORLD}/scene/info`) and in the
  model-spawn/bridge topics. A path-valued name fails the scene-info wait.
  Rejected after reading the script.
- **Free-running pre-start** (`gz sim -r` before PX4): previously tried;
  Gazebo advanced 7–9 s of sim time before PX4 attached, corrupting IMU/baro
  timestamps → EKF2 divergence → altitude runaway. This is documented in the
  header of `sim/launch/_start_gz_px4.sh:15-20`. Never pre-start unpaused
  without a late-unpause mechanism.
- **Paused pre-start with nothing to unpause it**: previously deadlocked the
  boot (same header). The missing piece was an explicit unpause after PX4
  attaches — that is what this plan adds.

### The viable mechanism

PX4's `else` branch ("gazebo already running") is a first-class supported path:
it adopts the detected world name and **never sources `gz_env.sh`**, so no
clobber. The plan: for repo-only worlds, pre-start a **paused** gz server
(`gz sim -s <abs-repo-world.sdf>` without `-r`), let PX4 detect and attach to
it, then unpause at the last safe moment so sim time barely advances before
PX4 is in lockstep.

One repo-side hazard to fix in the same change:
`sim_full.launch.py:79-99` (`_clock_bridge`) deliberately delays bridging the
gz clock "so PX4's rcS does not mis-detect a running world". Under pre-start
the world **is** running (by design), so that comment/mechanism still works
(the bridge only waits for `/world/<w>/clock` to appear) — but confirm the
bridge comes up on the pre-start path during verification.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Quality gate | `just check` | exit 0, all unit tests pass |
| Boot repo world | `just sim --world marker_field --overlay auto_arm` | verdict line `READY ...`, exit 0 |
| Boot default (regression) | `just sim` | `READY`, exit 0 |
| Watch logs | `rg src=px4 logs/latest.log` / `just log tail` | PX4 boot lines |
| Teardown | `just stop` | `STOPPED ... 0 survivors` |
| Full gate | `just test e2e` | all scenarios PASS, exit 0 |

Run everything from a Linux shell with ROS Jazzy (distrobox: `distrobox enter ubuntu -- bash -lc 'cd ~/Projects/ros-px4-template && <cmd>'`).

## Scope

**In scope** (the only files you should modify):
- `sim/launch/_start_gz_px4.sh` — add the pre-start-paused branch for repo worlds
- `sim/launch/sim_full.launch.py` — pass a `WORLD_IS_REPO` (or equivalent) flag; `_world_sdf` already computes it
- `tasks.py` — only if the `sim` command needs to forward the world to `wait_ready` differently (it already passes `--world` via the launch args; check before touching)
- `docs/SIM.md` — replace the "Limitations" blocker paragraph with the new boot mechanism
- `tests/unit/` — a unit test for any new pure helper you extract (e.g. world-classification)

**Out of scope** (do NOT touch):
- Anything under `PX4_DIR` (hard invariant; the whole point of this plan is to avoid it)
- `sim/worlds/*.sdf` — the worlds are already `gz sdf -k` valid (plan 043)
- The default-world boot path — it is flight-verified; the pre-start branch must be taken ONLY when the world SDF exists in `sim/worlds/`
- `tools/wait_ready.py` physics logic (plan 031 made it world-aware already)

## Git workflow

- Branch: `advisor/049-unblock-repo-worlds`
- Conventional commits (repo style, e.g. `fix(sim): boot repo-only worlds via pre-started paused gz server`)
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Thread a "repo world" flag into the boot script

In `sim_full.launch.py` `_gz_px4_stack`, `_world_sdf` already returns the
resolved SDF path and dir. Add to `additional_env`:
`"SIM_WORLD_SDF": _world_sdf_path` and `"WORLD_IS_REPO": "1" if the resolved
dir is the repo `sim/worlds` else ""` (compute from the existing return value;
rename the currently-underscore-discarded `_world_sdf_path` variable).

**Verify**: `just check` → exit 0.

### Step 2: Add the pre-start-paused branch to `_start_gz_px4.sh`

Keep the existing flow byte-identical when `WORLD_IS_REPO` is empty. When set:

```bash
if [ "$WORLD_IS_REPO" = "1" ]; then
  echo "[sim_full] Pre-starting paused gz server for repo world '$SIM_WORLD'"
  gz sim --verbose=1 -s "$SIM_WORLD_SDF" &        # NO -r: starts paused
  # Wait for the world to advertise its clock topic (PX4's own detection probe)
  for _ in $(seq 1 60); do
    gz topic -l 2>/dev/null | grep -qx "/world/${SIM_WORLD}/clock" && break
    sleep 0.5
  done
  # Unpause watcher: wait for PX4 to adopt the running world, then release physics.
  (
    for _ in $(seq 1 120); do
      if grep -q "gazebo already running world: ${SIM_WORLD}" <(tail -n 200 "$SESSION_LOG" 2>/dev/null) 2>/dev/null; then
        break
      fi
      sleep 0.5
    done
    # give the model spawn + gz_bridge attach a moment, then unpause
    sleep 1
    gz service -s "/world/${SIM_WORLD}/control" --reqtype gz.msgs.WorldControl \
      --reptype gz.msgs.Boolean --timeout 2000 --req 'pause: false'
    echo "[sim_full] repo world '${SIM_WORLD}' unpaused"
  ) &
fi
```

Notes for implementation (adapt, don't paste blindly):
- The PX4 stdout goes to the session log via the launch's process capture; if
  tailing the log is awkward from this script, an equally good unpause trigger
  is polling `gz model --list` (or the scene-info service) until the spawned
  model (`gz_${SIM_MODEL}` instance, e.g. `x500_0`) exists — that is the
  strongest "PX4 has attached and spawned" signal. Prefer the model-exists
  probe if the log path is not readily available in this script's env.
- Keep `GZ_SIM_RESOURCE_PATH` exports as they are — model/mesh resolution
  inside the SDF depends on them and PX4's `gz_env.sh` *appends* rather than
  clobbers that one.
- The `HEADLESS` handling must apply to the pre-started server too (`-s` is
  already server-only; the GUI, when not headless, is started by PX4's rcS
  only on the branch we're bypassing — for `--gui` on repo worlds, start
  `gz sim -g &` alongside, mirroring PX4's own rcS).

**Verify** (repo world boots): `just sim --world marker_field --overlay auto_arm`
→ verdict `READY` and exit 0. Then `rg "gazebo already running" logs/latest.log`
→ one match; `rg "unpaused" logs/latest.log` → one match.

### Step 3: Confirm flight is sane on the repo world (no runaway)

With the sim from Step 2 still up (auto_arm overlay arms and takes off):

**Verify**: after ~30 s, `rg src=controller logs/latest.log | tail -5` shows
`altitude_enu_m` stable near 3.0 (±0.3), NOT climbing monotonically. Also
`just log topics` → PASS (12 OK). Then `just stop` → `0 survivors`.

If altitude runs away or EKF errors appear (`rg -i "ekf" logs/latest.log`),
this is the IMU-timestamp failure mode — STOP condition 3.

### Step 4: Try the other two worlds + default regression

**Verify**:
- `just sim --world landing_pad` → READY; `just stop`.
- `just sim --world obstacle_course` → READY; `just stop`.
- `just sim` (default world — must take the ORIGINAL branch: `rg "Pre-starting paused" logs/latest.log` → no match) → READY; `just stop`.

### Step 5: Full regression + docs

Update `docs/SIM.md` "Limitations": remove the live-boot-blocked paragraph,
describe the pre-start-paused mechanism in 3-4 sentences (default world keeps
the PX4-starts-gz path; repo worlds pre-start paused + late unpause), and keep
the camera/perception limitation paragraph (that part is still true until
plan 062).

**Verify**: `just check` → exit 0. `just test e2e` → all scenarios PASS
(e2e uses the default world; this is the no-regression gate).

## Test plan

- Unit: if you extract a pure helper (e.g. classify world as repo/PX4), test it
  in `tests/unit/` following `tests/unit/test_sim_speed_validation.py`'s style.
  The heart of this plan is live-verified, not unit-verified.
- Live: Steps 2-5 above are the test plan; each has an explicit command+expected.

## Done criteria

- [ ] `just sim --world marker_field --overlay auto_arm` → READY, altitude holds ~3 m for 30 s, `just log topics` PASS
- [ ] `just sim --world landing_pad` and `--world obstacle_course` → READY
- [ ] `just sim` (default) → READY via the unchanged original branch
- [ ] `just check` exits 0; `just test e2e` all PASS
- [ ] `docs/SIM.md` no longer claims repo worlds cannot boot
- [ ] No file under `PX4_DIR` modified (`git -C $PX4_DIR status` → clean, if it's a git checkout)
- [ ] `plans/README.md`: this row DONE; plan 043's BLOCKED row annotated "unblocked by 049 — GUI sign-off may proceed"

## STOP conditions

Stop and report back (do not improvise) if:

1. The excerpts in "Current state" don't match the live `px4-rc.gzsim` /
   `gz_env.sh` (PX4 checkout differs from what this plan was written against).
2. PX4 does NOT print `gazebo already running world: <w>` on the pre-start
   path (its detection probe failed) — capture `rg src=px4 logs/latest.log`.
3. Altitude runaway or EKF divergence on a repo world after unpause (Step 3)
   — try moving the unpause earlier/later ONCE (model-exists probe vs.
   log-line probe); if both fail, STOP with both logs. Do not start tuning
   PX4 parameters.
4. Model spawn itself deadlocks while paused (PX4 stuck before "gazebo already
   running" completes and no model appears within 60 s) — report; the fallback
   design (unpause immediately after world detection) needs an operator
   decision because it re-opens a small free-run window.

## Maintenance notes

- Plan 062 (camera perception) builds directly on this: a camera-equipped
  model in a repo world needs this boot path.
- If PX4 is upgraded past v1.17, re-read `px4-rc.gzsim` — the detection probe
  and `gz_env.sh` behavior are unversioned internals.
- Reviewer should scrutinize: the unpause trigger's race window, and that the
  default-world path is byte-identical (diff the script's non-repo-world flow).
