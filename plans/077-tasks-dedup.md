# Plan 077: tasks.py dedup - shared boot path, e2e state seed, one log-clear, unified scenario command

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in "STOP conditions" occurs, stop and report - do not
> improvise. When done, update this plan's row in `plans/README.md`.
>
> **Drift check (run first)**: this plan is written against tasks.py AFTER
> plans 068 and 076 have landed. Confirm:
> - `rg '"speed"' tasks.py` returns nothing (068 removed the dead --speed
>   plumbing). If it still exists: STOP, land 068 first.
> - `rg "preflight.run|wait_ready.wait" tasks.py` returns hits (076 landed).
>   If not: STOP, land 076 first.
> The excerpts below quote the pre-068/076 shapes where the region is
> unchanged by them; reconcile small line drifts, but STOP on structural
> surprises.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: LOW-MED (pure restructuring inside one file; behavior pinned by
  verdicts, exit codes, and the live gates below)
- **Depends on**: 076 (hard), 068 (hard, same-file ordering)
- **Category**: simplification (complexity-reduction push, Round 7)
- **Planned at**: commit `d769ffe`, 2026-07-17

## Why this matters

tasks.py is 1310 lines with 139 branch statements (~20% of the repo's
non-test branches) and the only sub-A maintainability score in the repo.
Radon's worst offenders in it are not domain logic, they are copy-paste:

1. `sim()` and `hw()` are the same command twice: teardown-if-pidfile,
   preflight, smart-build, spawn, pid-write, wait, NOT READY teardown,
   READY verdict. Only the launch args, preflight mode, and verdict text
   differ (~50 duplicated lines).
2. `test(e2e, --detach)` seeds an e2e state dict that is a line-for-line copy
   of the one `_e2e_run` builds (~25 duplicated lines), kept in sync by hand.
3. The logs/ clear loop appears verbatim in `clean()` and `test(e2e)`.
4. `_e2e_sim_groups` converts each config dict into a 5-tuple that every
   consumer immediately unpacks back into named fields; since e2e went
   one-scenario-per-group (plans 053/064) the indirection carries no
   information.
5. `scenario()` has two branches (declared config / no config) that
   re-implement the same tail: run, summarize, digest-on-fail, exit.

## Tasks

### Task 1: shared sim/hw boot path

Add above `sim()`:

```python
def _prepare_stack(preflight_mode: str, build: bool, abort_msg: str) -> None:
    """Teardown any existing stack, preflight, then smart-build. Shared by sim/hw."""
    if (LOG_DIR / "sim.pid").exists():
        print("Existing stack found — tearing it down first.")
        _teardown()
    if not preflight.run(preflight_mode):
        print(abort_msg, file=sys.stderr)
        raise typer.Exit(int(ExitCode.PRECONDITION))
    _smart_build(build)


def _spawn_and_wait(
    launch_args: list[str], env: dict[str, str], timeout: int, fail_reason: str
) -> float:
    """Spawn the detached stack, record sim.pid, block until ready.

    Returns elapsed seconds; on NOT READY prints the verdict, tears down, and
    exits FAIL.
    """
    started = time.monotonic()
    proc = _spawn_stack(launch_args, env, append=False)
    (LOG_DIR / "sim.pid").write_text(str(proc.pid))
    ready = wait_ready.wait(timeout)
    elapsed = time.monotonic() - started
    if not ready:
        print(format_not_ready(fail_reason, elapsed), file=sys.stderr)
        _teardown()
        raise typer.Exit(int(ExitCode.FAIL))
    return elapsed
```

Rewrite `sim()` body as: overlay validation (068's filesystem-based check,
unchanged, still first so usage errors precede teardown), then

```python
    _prepare_stack("headless", build, "Preflight failed. Aborting launch.")
```

then the existing `gz_resource` / `vision_arg` / `headless_val` /
`overlay_args` / `launch_args` / `env` composition (unchanged), then

```python
    elapsed = _spawn_and_wait(
        launch_args, env, timeout, "stack did not reach readiness (topics/rosbridge/GCS params)"
    )
```

then the existing `--record` block and `format_ready` print, using `elapsed`.
Delete the now-dead `import time as _time` local and the inline
started/spawn/pid/wait/NOT-READY lines it replaces.

Rewrite `hw()` the same way: vehicle-overlay validation first (unchanged),
then `_prepare_stack("hw", build, "Preflight failed. Aborting hardware launch.")`,
then the existing `print(f"Connecting to hardware on {port} at {baud} baud...")`
and `launch_args`/`env` composition, then

```python
    elapsed = _spawn_and_wait(
        launch_args, env, timeout, "hardware stack did not reach readiness (topics/rosbridge)"
    )
    print(format_ready([f"FC {port}@{baud}", "rosbridge:9090", "/fmu topics up"], elapsed))
```

Print-order note (this is the one visible reordering): today `hw()` prints
"Connecting to hardware..." BEFORE smart-build output; after this change it
prints AFTER (prepare runs first). `sim()` has no such print. This is a
cosmetic progress line, not a verdict; accepted. If the maintainer objects,
move the print before `_prepare_stack` instead - do not restructure further.

- [ ] Step 1: apply; delete the duplicated blocks
- [ ] Step 2: `just check` passes
- [ ] Step 3: live: `just sim` READY verdict identical (modulo timing);
      `just sim` again exercises the teardown-first path
      ("Existing stack found"); `just stop` clean
- [ ] Step 4: commit `refactor(tasks): single boot path shared by sim and hw`

### Task 2: one e2e state seed, no tuple indirection

Add near `_e2e_write_state`:

```python
def _e2e_initial_state(configs: list[dict]) -> dict:
    """Fresh e2e progress state: one isolated sim group per declared scenario."""
    return {
        "status": "running",
        "started_at": time.time(),
        "finished_at": None,
        "groups": [
            {
                "vision": c["vision"],
                "overlay": c["overlay"],
                "model": c["model"],
                "world": c["world"],
                "scenarios": [c["scenario"]],
                "state": "pending",
                "fails": 0,
            }
            for c in configs
        ],
    }
```

In `_e2e_run`: replace the `group_items = _e2e_sim_groups(configs)` + inline
`state = {...}` block with `state = _e2e_initial_state(configs)` and
`_e2e_write_state(state)`; replace the group loop header with

```python
        for idx, cfg in enumerate(configs):
```

and the group call with

```python
            group_fails = _run_e2e_sim_group(
                cfg["vision"],
                cfg["overlay"],
                [cfg["scenario"]],
                gz_resource=gz_resource,
                model=cfg["model"],
                world=cfg["world"],
                audit_topics=idx == len(configs) - 1,
            )
```

In `test(e2e, --detach)`: replace the `group_items = _e2e_sim_groups(configs)`
+ inline seed dict with

```python
        _e2e_write_state(_e2e_initial_state(configs))
```

and `n = len(group_items)` with `n = len(configs)` in the E2E STARTED line.

Delete `_e2e_sim_groups` entirely.

The state JSON written to `logs/e2e_state.json` must be KEY-FOR-KEY identical
to today's (e2e_status/reports parse it); the helper above preserves every key
and value.

- [ ] Step 1: apply
- [ ] Step 2: `uv run pytest tests/unit/ -q` (test_tasks_e2e_groups.py may
      reference `_e2e_sim_groups`; if so, retarget it at
      `_e2e_initial_state`'s `groups` list - same assertions on
      vision/overlay/model/world/scenarios per group)
- [ ] Step 3: commit `refactor(tasks): single e2e state seed; drop the group-tuple indirection`

### Task 3: one log-clear helper

```python
def _clear_log_dir() -> None:
    """Wipe logs/ except .gitkeep (per-run artifacts only; build cache untouched)."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    for f in LOG_DIR.glob("*"):
        if f.name != ".gitkeep":
            if f.is_file() or f.is_symlink():
                f.unlink()
            elif f.is_dir():
                shutil.rmtree(f)
```

Use it in `clean()` (replacing its loop; keep the surrounding
build/install/log rmtree and prints) and in `test(e2e)` (replacing the loop
under "Clearing previous simulation logs...", keeping that print).

- [ ] Step 1: apply; `just check`
- [ ] Step 2: commit `refactor(tasks): shared _clear_log_dir`

### Task 4: unify scenario()

Replace the body of `scenario()` with (docstring unchanged):

```python
    _smart_build(True)
    script = _resolve_scenario_script(name)
    cfg = _resolve_scenario_config(name)
    if cfg is None:
        print(
            f"No declared sim config for '{name}' in tests/capabilities.toml — "
            "running against the existing sim (start one with `just sim` first). "
            f"To make `just scenario {name}` boot the right sim, add the entry "
            'with platforms = ["sim"] (see `just scenario-new` output).'
        )
        print(f"Running scenario test: {name}...")
        try:
            result = subprocess.run(["uv", "run", "python", str(script)], cwd=str(ROOT))
            fails = 0 if result.returncode == 0 else 1
        finally:
            _summarize_logs_silent()
    else:
        print(f"Tearing down any existing stack before booting {name}'s declared sim...")
        _teardown()
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        (LOG_DIR / "latest.log").write_text("", encoding="utf-8")
        try:
            fails = _run_e2e_sim_group(
                cfg["vision"],
                cfg["overlay"],
                [cfg["scenario"]],
                gz_resource=f"{ROOT}/sim/worlds:{ROOT}/sim/models",
                model=cfg["model"],
                world=cfg["world"],
            )
        finally:
            _summarize_logs_silent()
    if fails:
        _print_failure_digest()
        raise typer.Exit(int(ExitCode.FAIL))
```

Semantics preserved: unknown scenario still exits USAGE via
`_resolve_scenario_script` before any teardown; both paths summarize in a
`finally`; failure prints the digest and exits FAIL; success exits 0.

- [ ] Step 1: apply; `just check`
- [ ] Step 2: live: `just scenario 01_arm_takeoff` PASS;
      `just scenario nope` exits 2 with the Available list
- [ ] Step 3: commit `refactor(tasks): one scenario() tail for declared and ad-hoc runs`

### Task 5: check() static-step loop

In `check()`, replace the two sequential ruff subprocess blocks with:

```python
    print("Running ruff format and lint auto-fixes")
    for label, argv in (
        ("ruff check", ["uv", "run", "ruff", "check", "--fix", *ruff_paths_str]),
        ("ruff format", ["uv", "run", "ruff", "format", *ruff_paths_str]),
    ):
        if subprocess.run(argv, cwd=str(ROOT), env=env).returncode != 0:
            failed_steps.append(label)
```

(The invariants/docs steps are already in-process calls from 076; the ty and
pytest steps keep their existing shapes.)

- [ ] Step 1: apply; `just check` output ordering identical
- [ ] Step 2: commit `refactor(tasks): table-drive the ruff pair in check()`

### Task 6: final gate + metrics

- [ ] `just test e2e` - all 8 PASS, exit 0
- [ ] `just e2e-status` after completion - aggregate block, exit 0
- [ ] Record the metric delta in the commit message:
      `wc -l tasks.py` (expect roughly 1310 -> ~1150 or lower after 076+077) and
      `uvx radon cc -s tasks.py | tail -3` (average should drop; no new C+
      functions)
- [ ] Update `plans/README.md` row

## STOP conditions

- Any difference in `logs/e2e_state.json` keys vs a pre-change run: STOP
  (e2e-status parses it).
- Any verdict line or exit code changes in the live gates: STOP.
- If 068's landed `sim()` overlay validation conflicts structurally with
  Task 1's rewrite: reconcile by keeping 068's validation code verbatim at the
  top of `sim()`; if that is not cleanly possible, STOP.

## Explicitly out of scope (investigated, keep as-is)

- `_source_workspace_env` (CC 17): the JSON env cache keyed on
  `install/setup.bash` mtime is what makes the post-build re-source correct
  AND fast (plan 039). Any "simpler" AMENT_PREFIX_PATH shortcut breaks the
  rebuild case. Do not touch.
- `_get_clean_env` / `_ros_launch_env`: each branch documents a real footgun
  (uv venv shadowing system Python for ROS nodes). Necessary complexity.
- The e2e supervisor structure itself (detach/worker/state files): Round 6
  already rejected extracting it; this plan only dedupes inside it.
