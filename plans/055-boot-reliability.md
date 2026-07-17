# Plan 055: Boot reliability — teardown-before-preflight, stale READY-flag, arming-param parity

> **Executor instructions**: Follow this plan step by step, verifying each
> step. On any STOP condition, stop and report. When done, update
> `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 01f94c7..HEAD -- tasks.py tools/preflight.py tools/wait_ready.py tools/gcs_heartbeat.py tools/sim_cleanup.py sim/launch/_start_gz_px4.sh`
> On any mismatch with the excerpts below, STOP.

## Status

- **Priority**: P2
- **Effort**: S (three small, independent fixes)
- **Risk**: LOW
- **Depends on**: none. Plan 056 (param ack) touches `gcs_heartbeat.py` too — land 055 first.
- **Category**: bug (tooling)
- **Planned at**: commit `01f94c7`, 2026-07-10

## Why this matters

Three boot-path defects each cost an autonomous agent a debugging round-trip:

1. **`just sim` is not idempotent as documented.** Preflight (which fails on
   occupied ports 8888/9090) runs BEFORE the "tear down any existing stack"
   step, so re-running `just sim` while a stack is up aborts at preflight
   instead of recycling the stack. The docstring promises idempotency; the
   code can only deliver it in the odd state where `sim.pid` exists but ports
   are free.
2. **Stale `/tmp/gcs_params_flag` can false-READY a fresh boot.** `wait_ready`
   treats the flag's existence as "PX4 params committed", but the flag is only
   deleted by `sim_cleanup.teardown()`. After an unclean exit (no `sim.pid`,
   flag left behind), the next boot's standby gate passes instantly — READY
   can be declared before this boot's PX4 is actually responsive.
3. **The two arming-param lists have drifted.** Boot-time env exports set 5
   params including `EKF2_GPS_CTRL=7`; the runtime GCS overlay re-sends only
   4 (no `EKF2_GPS_CTRL`). If PX4 restarts mid-session (the re-send path),
   the param sets differ from a fresh boot — a latent source of
   hard-to-reproduce arming/EKF behavior differences.

## Current state

1. `tasks.py:560-571` (`sim()`; `hw()` at `:733-745` has the same order):

   ```python
   # Preflight (precondition class).
   res = subprocess.run(
       ["uv", "run", "python", "tools/preflight.py", "--mode=headless"], cwd=str(ROOT)
   )
   if res.returncode != 0:
       print("Preflight failed. Aborting launch.", file=sys.stderr)
       raise typer.Exit(int(ExitCode.PRECONDITION))

   # Idempotent: cold-tear-down any existing stack, then boot fresh.
   if (LOG_DIR / "sim.pid").exists():
       print("Existing stack found — tearing it down first.")
       _teardown()
   ```

   `tools/preflight.py:116-134` — headless/hw modes fail when port 8888 or
   9090 is in use ("already in use … run: just sim-stop").

2. `tools/wait_ready.py:110-117` — `_px4_standby()` returns
   `Path("/tmp/gcs_params_flag").exists()`; the flag is written by
   `tools/gcs_heartbeat.py:98` (`_PARAMS_FLAG.write_text(str(time.time()))`)
   and deleted only at `tools/sim_cleanup.py:198`
   (`Path("/tmp/gcs_params_flag").unlink(missing_ok=True)` inside teardown).

3. `sim/launch/_start_gz_px4.sh` exports (boot-time, authoritative per its
   own comment "Applied at STARTUP (reliable)"):
   `PX4_PARAM_COM_ARM_WO_GPS=1`, `PX4_PARAM_CBRK_SUPPLY_CHK=894281`,
   `PX4_PARAM_COM_SPOOLUP_TIME=0.0`, `PX4_PARAM_EKF2_GPS_CHECK=0`,
   `PX4_PARAM_EKF2_GPS_CTRL=7`.
   `tools/gcs_heartbeat.py:22-30` `_PARAMS` tuple: `COM_ARM_WO_GPS`,
   `CBRK_SUPPLY_CHK`, `COM_SPOOLUP_TIME`, `EKF2_GPS_CHECK` — no
   `EKF2_GPS_CTRL`.

Existing tests: `tests/unit/test_preflight.py` (6),
`tests/unit/test_gcs_heartbeat.py` (5), `tests/unit/test_wait_ready.py`,
`tests/unit/test_sim_cleanup.py` — extend these, matching their patterns.

## Commands you will need

| Purpose | Command | Expected |
|---------|---------|----------|
| Quality gate | `just check` | exit 0 |
| Targeted | `uv run pytest tests/unit/test_wait_ready.py tests/unit/test_gcs_heartbeat.py tests/unit/test_preflight.py -q` | all pass |
| Idempotency (live) | `just sim && just sim` | second call recycles + READY, exit 0 |
| Teardown | `just stop` | `0 survivors` |

## Scope

**In scope**:
- `tasks.py` (`sim()` and `hw()` ordering only)
- `tools/wait_ready.py` (mtime-based freshness for the flag)
- `tools/gcs_heartbeat.py` (add `EKF2_GPS_CTRL` to `_PARAMS` + a parity comment)
- `sim/launch/_start_gz_px4.sh` (parity comment only — values unchanged)
- `tests/unit/` extensions

**Out of scope**:
- Replacing the `/tmp` flag path (deferred SECURITY-01, plans index Round 4) —
  keep the path, fix the freshness
- Any PARAM ack/read-back mechanism — that is plan 056
- `sim_cleanup.py` logic

## Git workflow

- Branch: `advisor/055-boot-reliability`
- Commit per fix (3 commits), style: `fix(sim): tear down existing stack before preflight`, etc.

## Steps

### Step 1: Teardown before preflight (fix 1)

In `tasks.py` `sim()`: move the `if (LOG_DIR / "sim.pid").exists(): _teardown()`
block ABOVE the preflight `subprocess.run`. Keep the argument-validation block
(`--speed`, `--overlay` checks, `:550-558`) first — cheap usage errors should
not trigger a teardown. Apply the same reorder in `hw()`.

Also handle the pidless-orphan case the reorder exposes: if preflight STILL
fails on ports after the conditional teardown (crashed stack without
`sim.pid`), the error message is now accurate ("run: just sim-stop") — no
further change needed; do NOT add an unconditional teardown (a user may have
an unrelated service on 9090; killing it implicitly is worse).

**Verify (live)**: `just sim` → READY; then `just sim` again → prints
"Existing stack found — tearing it down first.", preflight passes, READY,
exit 0. `just stop`.

### Step 2: Flag freshness in `wait_ready` (fix 2)

Give `_px4_standby()` a launch-start reference: in `main()`, record
`start = time.time()` before the poll loop and pass it down; the gate becomes:

```python
def _px4_standby(not_before: float) -> bool:
    try:
        return _GCS_PARAMS_FLAG.stat().st_mtime >= not_before
    except FileNotFoundError:
        return False
```

The flag content is already a `time.time()` string (`gcs_heartbeat.py:98`),
but mtime is simpler and immune to content-format drift. Since `wait_ready`
starts after the launch spawns (see `tasks.py` sim flow / `_run_e2e_sim_group`
`:828-843`), `wait_ready`'s own start time is a safe `not_before` — a flag
written by a PREVIOUS session is always older.

Update the docstring lines `wait_ready.py:8-9` and `110-116` to say
"fresh flag (mtime after this waiter started)".

Extend `tests/unit/test_wait_ready.py`: stale flag (mtime in the past via
`os.utime`) → standby False; fresh flag → True; missing → False. Match the
existing test file's monkeypatch style for `_GCS_PARAMS_FLAG` (it already
tests around the flag; read it first).

**Verify**: `uv run pytest tests/unit/test_wait_ready.py -q` → all pass.

### Step 3: Param parity (fix 3)

Add `("EKF2_GPS_CTRL", 7, "INT32"),` to `_PARAMS` in `gcs_heartbeat.py` and a
comment on the tuple: `# Keep in lockstep with the PX4_PARAM_* exports in
sim/launch/_start_gz_px4.sh (boot-time authoritative copy).` Add the mirror
comment in `_start_gz_px4.sh` above its export block pointing back at
`tools/gcs_heartbeat.py:_PARAMS`.

Add a parity unit test in `tests/unit/test_gcs_heartbeat.py`: parse
`sim/launch/_start_gz_px4.sh` for `^export PX4_PARAM_(\w+)=(.+)$` and assert
the name set equals `{name for name, _, _ in gcs_heartbeat._PARAMS}` — the
drift class dies permanently.

**Verify**: `uv run pytest tests/unit/test_gcs_heartbeat.py -q` → all pass
(now ≥6). Kill-test: comment out the new tuple line, rerun → parity test
fails naming `EKF2_GPS_CTRL`; restore.

### Step 4: Full gates

**Verify**: `just check` → exit 0. Live: `just sim` → READY;
`just scenario 01_arm_takeoff` → PASS; `just stop` → 0 survivors.

## Done criteria

- [ ] `just sim` twice in a row: second run recycles and reaches READY (live)
- [ ] Stale-flag unit tests pass; `wait_ready` gates on mtime ≥ waiter start
- [ ] Parity test passes and fails when a param is removed from either list (kill-test shown)
- [ ] `just check` exit 0; `just scenario 01_arm_takeoff` PASS
- [ ] `plans/README.md` row updated

## STOP conditions

- `wait_ready` is invoked anywhere BEFORE the stack spawn (grep
  `wait_ready` in `tasks.py`) in a way that breaks the `not_before`
  assumption — report the call site.
- The parity regex misses params because `_start_gz_px4.sh` formats exports
  differently than `^export PX4_PARAM_...` — adjust the regex to the actual
  file, and if exports are conditional (inside `if` blocks), include them
  and note it in the test.

## Maintenance notes

- Plan 056 (param ack) builds on the same `_PARAMS` tuple; its read-back loop
  must cover the 5th param added here.
- Anyone adding a PX4 param override must now add it in ONE place and the
  parity test names the other.
