# Plan 007: `just scenario <name>` runs against the scenario's declared sim config

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat 9f5ba74..HEAD -- tasks.py tests/capabilities.toml`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: MED
- **Depends on**: none
- **Category**: dx
- **Planned at**: commit `9f5ba74`, 2026-06-21

## Why this matters

Running a single scenario manually silently tests the wrong thing. `just sim`
boots the **demo** mission (`config/params/sim.yaml` sets
`mission_file: config/missions/demo.yaml`), which arms and *flies a multi-phase
path*. But `tests/capabilities.toml` declares that `01_arm_takeoff` needs
`sim_overlay = "hover"` (a stationary hold at z=3, `config/missions/hover.yaml`,
whose header literally says "Used by 01_arm_takeoff / 02_hover_hold"). The e2e
harness honors that: it boots an isolated sim per `(vision, overlay)` config via
`scenario_sim_configs("sim")` (`tasks.py:734`), with a comment at `tasks.py:732`
warning that the hover scenario "must not share a sim with the auto-flown demo
mission". But `just scenario <name>` (`tasks.py:784-802`) does **not** — it just
smart-builds and runs the script against whatever sim happens to be up. So
`just sim` then `just scenario 01_arm_takeoff` runs 01 against the demo mission:
the drone is translating, the scenario anchors a hold point and sees the drone
fly away, and you get a confusing `position drift` FAIL even though arm,
takeoff, OFFBOARD handoff, and altitude hold all worked. This was observed live
on 2026-06-21 (FAIL `drift`, `mission_phase=follow`, anchor x≈3.3) and it
reproduces identically regardless of unrelated code — it is purely the
mission/overlay mismatch. After this plan, `just scenario <name>` boots the sim
the scenario actually declares, so a manual single run matches e2e and passes.

## Current state

- `just scenario <name>` → `tasks.py:784-802`:
  ```python
  def scenario(name: str = typer.Argument(...)) -> None:
      """Run a live scenario test directly by name."""
      _smart_build(True)
      script = _resolve_scenario_script(name)
      print(f"Running scenario test: {name}...")
      passed = False
      try:
          result = subprocess.run(["uv", "run", "python", str(script)], cwd=str(ROOT))
          passed = result.returncode == 0
      finally:
          _summarize_logs_silent()
      if not passed:
          raise typer.Exit(int(ExitCode.FAIL))
  ```
  It assumes a correctly-configured sim is already running. Run cold (no sim) it
  fails with empty `controller_state` (no nodes); run against the default demo
  sim it fails `drift`.
- Per-scenario sim config lives in `tests/capabilities.toml`. The `01_arm_takeoff`
  entry includes `scenario_file = "01_arm_takeoff.py"`, `sim_vision = "none"`,
  `sim_overlay = "hover"`. `02_hover_hold` likewise uses `sim_overlay = "hover"`.
- `scenario_sim_configs("sim")` (imported at `tasks.py:155` from `capabilities`,
  used at `tasks.py:734`) returns the e2e config groups. The e2e launch path
  (around `tasks.py:602-640`, the `_run_one_config`/`_spawn_stack` helpers used
  by the e2e command) already knows how to boot one headless sim for a given
  `(vision, overlay)`, wait for readiness, run that group's scenarios, and tear
  down. **Reuse that machinery — do not invent a second launch path.**
- The overlay name maps to a real param file: `config/params/overlays/hover.yaml`
  (and `auto_arm.yaml`, `marker_hover.yaml`, `search_relocalize.yaml`). `just sim
  --overlay hover` already wires `param_overlay:=hover` into the launch
  (`tasks.py:485` builds `overlay_args`).
- The detached-sim + English-verdict + exit-code contract is described in
  `AGENTS.md` ("Command verdicts and exit codes", "just sim always detaches").
  Any sim this command boots must be torn down before it returns (no orphan),
  matching `just stop` semantics. Look at how the e2e command brackets
  boot/run/teardown and mirror it.

Read these before writing code: the `e2e` command body and its config-group
loop in `tasks.py` (the function that calls `scenario_sim_configs`), the
`_spawn_stack` helper (`tasks.py:188`), the readiness wait it uses, and
`capabilities.py`'s `scenario_sim_configs` so you know the exact shape returned
(fields per scenario: at least `scenario_file`, `sim_vision`, `sim_overlay`).

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Build + lint + typecheck | `just check` | exits 0, `all checks passed.` (may need `src/px4_msgs`; if missing, see note) |
| Cold single scenario (DECISIVE, needs sim) | `just stop` then `just scenario 01_arm_takeoff` | boots a hover sim, scenario prints `PASS`, sim torn down, exit 0 |
| No orphans after | `just status` or `pgrep -fa px4` | no leftover sim/px4 process |
| Config lookup sanity | `uv run python -c "import sys; sys.path.insert(0,'tools'); from capabilities import scenario_sim_configs; print([c for c in scenario_sim_configs('sim')])"` | prints configs incl. 01_arm_takeoff with overlay hover |

## Scope

**In scope**:
- `tasks.py` — the `scenario(name)` command (`:784-802`) and any small private
  helper you add for "boot the sim a scenario declares, run it, tear down".
- `plans/README.md` (status row only — skip if a reviewer owns the index).

**Out of scope** (do NOT touch):
- The scenario scripts under `tests/scenarios/` and their thresholds
  (`_XY_TOL`, etc.). The drift FAIL is a mission mismatch, NOT a tolerance bug —
  do not loosen tolerances to paper over it.
- `tests/capabilities.toml` data — read it, do not edit the declared configs.
- The `e2e` command itself and `_spawn_stack`/readiness helpers — reuse them,
  do not modify their behavior.
- `config/missions/*` and `config/params/*` — the missions/overlays are correct.
- Flight control / `nodes/` — there is no flight bug here.

## Git workflow

- Branch: `advisor/007-scenario-self-configures-sim`
- Commit style: conventional commits. Suggested message:
  `feat(scenario): boot the sim config a scenario declares, not the default`.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Look up the scenario's declared sim config

In `scenario(name)`, before running, resolve the scenario's `(sim_vision,
sim_overlay)` from `capabilities.toml` via `scenario_sim_configs("sim")` (match
on `scenario_file == f"{name}.py"` or the entry whose scenario maps to `name`;
follow the exact field names that function returns — confirm by reading
`capabilities.py`). If no capability entry matches `name`, fall back to the
current behavior (run against the existing sim) and print a clear note that no
declared config was found, so unknown/ad-hoc scenarios still work.

**Verify**: the config-lookup command in the table prints a config for
`01_arm_takeoff` with overlay `hover`.

### Step 2: Boot that sim, run the scenario, tear down

When a declared config is found, bracket the run exactly like the e2e command
does for one config group:
1. tear down any existing sim first (call the same teardown `just stop` uses, so
   you never inherit a demo sim) — a clean slate is the whole point;
2. boot one headless sim with that scenario's `vision` + `overlay` (reuse the
   e2e per-config launch helper / `_spawn_stack` with the overlay args, the same
   way `tasks.py:485` builds `overlay_args`);
3. wait for readiness using the existing readiness wait (do not hand-roll one);
4. run `uv run python <script>` as today;
5. in a `finally`, tear the sim down so the command leaves no orphan, then
   `_summarize_logs_silent()` as today.

Preserve the exit-code contract: scenario PASS → exit 0; FAIL → `ExitCode.FAIL`;
a readiness failure before the scenario runs → a NOT READY verdict and the
precondition exit code, never a false pass.

**Verify** (DECISIVE, needs sim): `just stop` then `just scenario 01_arm_takeoff`
boots a hover sim on its own and the scenario prints `PASS`; afterward
`pgrep -fa px4` shows no leftover process. If you cannot run the sim here (no
`PX4_DIR`/Gazebo), complete Step 1 + `just check`, then STOP and report Step 2 as
"pending operator sim verification".

### Step 3: Quality gate

**Verify**: `just check` exits 0 and ends with `all checks passed.` (If it fails
only at the branch-invariants step with `Missing src/px4_msgs`, that is a
pre-existing worktree setup gap unrelated to this change — note it; the
lint/typecheck stage covering `tasks.py` must still pass.)

## Test plan

- The config-resolution logic is the unit-testable core. If it is cleanly
  factored (a helper that maps a scenario name to its `(vision, overlay)` from
  `scenario_sim_configs`), add a small unit test under `tests/unit/` modeled on
  an existing pure test (e.g. `tests/unit/test_check_topics.py`) asserting
  `01_arm_takeoff` resolves to overlay `hover` and an unknown name resolves to
  the "no declared config" fallback. If the logic cannot be unit-tested without a
  live sim, say so and rely on the Step 2 live gate.
- Decisive live gate: `just scenario 01_arm_takeoff` self-boots a hover sim and
  PASSes (operator-run if sim unavailable in the executor env).

## Done criteria

ALL must hold:

- [ ] `just scenario <name>` resolves the scenario's overlay/vision from `capabilities.toml`
- [ ] With a declared config, it boots that sim, runs, and tears it down (no orphan)
- [ ] Unknown scenario names fall back to the old run-against-existing behavior with a clear note
- [ ] `just scenario 01_arm_takeoff` from cold prints `PASS` (or Step 2 reported "pending operator sim verification")
- [ ] `just check` exits 0 (or only the pre-existing `src/px4_msgs` gap blocks it)
- [ ] No files outside the in-scope list are modified (`git status`)
- [ ] `plans/README.md` status row for 007 updated (unless a reviewer owns the index)

## STOP conditions

Stop and report back (do not improvise) if:

- `scenario_sim_configs` does not expose per-scenario `sim_overlay`/`sim_vision`
  (its shape changed since this plan was written) — report the actual shape.
- Booting the sim from `scenario()` would require duplicating large parts of the
  e2e launch path rather than reusing a shared helper — report it; the intent is
  reuse, and a big copy-paste is a design smell worth a second look.
- `just scenario 01_arm_takeoff` still FAILs `drift` even when booted with the
  hover overlay — that would mean a real station-keeping problem, a genuine
  control finding for the operator, not something to fix by loosening tolerances.
- You cannot run a sim at all — finish Step 1 + `just check`, report Step 2/the
  live gate as pending operator verification.

## Maintenance notes

- This makes `just scenario <name>` self-contained (boot + run + teardown),
  matching e2e semantics. For tight iteration where you want to keep one sim up
  across many runs, the workflow becomes `just sim --overlay <x>` then run the
  scenario script directly (`uv run python tests/scenarios/<name>.py`); note that
  in the recipe's help or `AGENTS.md` if it is not already obvious.
- A reviewer should confirm the teardown runs even when the scenario raises, so
  the command never leaves an orphan sim (the existing `finally` must wrap both
  the run and the teardown).
- The plan-005 doc and any other place that says "`just sim` then
  `just scenario 01_arm_takeoff`" as a verification recipe is now slightly off —
  after this change the single command is self-sufficient. Not in scope to chase
  every mention, but worth a note in review.
