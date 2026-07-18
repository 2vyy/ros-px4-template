# Plan 076: One Python environment - tasks.py joins the project venv; tools run in-process

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in "STOP conditions" occurs, stop and report - do not
> improvise. When done, update this plan's row in `plans/README.md`.
>
> **Drift check (run first)**:
> `git diff --stat d769ffe..HEAD -- tasks.py justfile pyproject.toml tools/preflight.py tools/wait_ready.py tools/check_invariants.py tools/check_docs.py tools/check_topics.py`
> Plan 068 landing first is EXPECTED drift (it edits `tools/preflight.py`,
> `tools/e2e_status.py`, `tasks.py` in regions this plan mostly avoids); on 068
> drift, reconcile line numbers and continue. Any OTHER mismatch with the
> "Current state" excerpts below: STOP.

## Status

- **Priority**: P1 (enabler for 077/078)
- **Effort**: M
- **Risk**: MED (touches the launch path of every command; live e2e gate at the end)
- **Depends on**: none hard. 068 recommended first (it edits `tools/preflight.py` and `tasks.py`; landing 068 first avoids rebasing it)
- **Category**: simplification (complexity-reduction push, Round 7)
- **Planned at**: commit `d769ffe`, 2026-07-17

## Why this matters

The repo currently runs TWO Python environments:

1. `tasks.py` in uv **script mode** (`# /// script` inline deps: typer, rich,
   tomli-w, pyyaml, numpy).
2. Everything else in the **project venv** (`pyproject.toml`, a strict
   superset of the inline list).

Because the task runner lives in a different env than the tools, it shells out
`uv run python tools/<x>.py` ten different ways (preflight, wait_ready,
e2e_report, e2e_status, status, scenario_status, check_topics,
check_invariants, check_docs, log via shim) even though it ALREADY imports
seven tools directly (bag_recorder, sim_cleanup, skein_analyze, ulog_retrieve,
capabilities, cli_verdict, log_summary, mission_cli, scenario_scaffold). The
split buys nothing: the inline dep list is a subset of the project deps, and
`justfile:_run` sources ROS + workspace before either env starts.

Round 4b deferred "env-sourcing consolidation" until after plans 039+045; both
are DONE. This plan collapses the two environments into one and converts the
subprocess hops into imports. Payoff:

- One dependency list (delete the inline `# /// script` block and its
  keep-in-lockstep comment discipline).
- ~10 fewer `uv run` process spawns per e2e cycle (each costs interpreter +
  uv resolution startup), several per `just sim`.
- The tool `main()` shims stop being process boundaries, which is what makes
  the 077/078 dedup possible.

Behavior contract that must NOT change: every verdict line, exit code, print
order, and the env each subprocess (colcon/ruff/ty/pytest/scenarios/launch)
receives. Scenario scripts and the detached e2e worker STAY subprocesses
(crash isolation, process-group teardown); only pure "run python tool, check
returncode" hops become calls.

## Current state

- `tasks.py:1-14`: `#!/usr/bin/env uv run` + `# /// script` block with 5 deps.
- `tasks.py:193-204`: `sys.path.append(str(ROOT / "tools"))` then direct
  imports of 9 tool modules (precedent for in-process use).
- Subprocess hops to convert (all `uv run python tools/...` + returncode
  checks): `sim()` preflight (~line 680) and wait_ready (~714); `hw()`
  preflight (~872) and wait_ready (~897); `test e2e` preflight (~1107);
  `_run_e2e_sim_group` wait_ready (~965) and check_topics audit (~1018);
  `_e2e_run` e2e_report (~374); `e2e_status_cmd` (~1183); `status()` (~1281);
  `scenario_status()` (~1289); `topics()` (~1303); `check()` invariants (~595)
  and check_docs (~602).
- `justfile:20`: `uv run tasks.py "$@"` - with the script block removed, uv
  runs the same file in the PROJECT environment. No justfile change needed.
- `pyproject.toml:20`: comment "tasks.py runs in uv script mode with its own
  smaller inline dep list".
- Tool entry points today: `preflight.main()` argparses + `sys.exit`;
  `wait_ready.main()` is a typer command that `typer.Exit(0)`/`sys.exit(1)`;
  `check_invariants.main()` exits 1 or prints pass; `check_docs.main(argv)`
  raises `SystemExit(1)` on failure (tests call it with `argv`);
  `check_topics.main()` is a typer command; `e2e_report.build_block`,
  `e2e_status.build_status`, `scenario_status.format_scenario_status`,
  `status.main` are already importable.
- Tests import the pure functions (`test_wait_ready` uses `CliRunner` on
  `wait_ready.app`; `test_check_docs` calls `check_docs.main(["--root", ...])`
  expecting `SystemExit`); both interfaces are preserved below.

## Tasks

### Task 1: delete the inline script env

`tasks.py`: replace lines 1-14 with:

```python
#!/usr/bin/env uv run
# Runs in the project venv (pyproject.toml). `just _run` invokes `uv run
# tasks.py`, which resolves the project environment now that there is no
# inline script metadata.
# ruff: noqa: E402,S603
```

`pyproject.toml`: replace the line-20 comment with:

```toml
# tasks.py runs in this same project environment (uv run tasks.py).
```

Verify immediately (this alone must not break anything):

```
just check          # expect: all checks passed, 383 tests
uv run tasks.py --help   # expect: typer help, no import errors
```

- [x] Step 1: apply both edits
- [x] Step 2: run the two commands above, confirm output
- [x] Step 3: commit `refactor(env): tasks.py runs in the project venv (drop inline script deps)`

### Task 2: give the four checker tools a callable seam

Keep every existing CLI surface (same flags, same exit codes) so direct
invocation and unit tests keep working; add a `run(...)` that returns instead
of exiting.

**`tools/preflight.py`**: rename `main()` to `run(mode: str = "gui") -> bool`;
replace the argparse block at its top with the `mode` parameter, replace every
`args.mode` with `mode`, and replace the final
`sys.exit(0 if all_ok else 1)` with `return all_ok` (keep the
"Preflight OK."/"Preflight FAILED" prints inside `run`). Add:

```python
def main() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", default="gui")
    args = parser.parse_args()
    sys.exit(0 if run(args.mode) else 1)
```

**`tools/wait_ready.py`**: move the body of the typer `main` into
`def wait(timeout: int = 180) -> bool:` with `raise typer.Exit(0)` replaced by
`return True` and the trailing `sys.exit(1)` (after the TIMEOUT echo) replaced
by `return False`. The typer command becomes:

```python
@app.command()
def main(
    timeout: int = typer.Option(180, "--timeout", help="Seconds before giving up"),
) -> None:
    if not wait(timeout):
        sys.exit(1)
```

**`tools/check_invariants.py`**:

```python
def run() -> bool:
    ok = check_px4_msgs_branch()
    if ok:
        print("All invariant checks passed.")
    return ok


def main() -> None:
    if not run():
        sys.exit(1)
```

**`tools/check_docs.py`**: split `main` so the loop body lives in
`def run(root: Path, verbose: bool = False) -> int:` returning `failed`
(keep all prints, including the FAILED/OK summary lines, inside `run`);
`main(argv)` keeps its exact signature and `raise SystemExit(1)` when
`run(...)` returns nonzero (the `test_check_docs.py` `SystemExit` tests must
pass unmodified).

**`tools/check_topics.py`**: move the body of the typer `main` into
`def run(manifest: Path, *, dry_run: bool = False, source_dir: Path = Path("."), vision: bool = False) -> int:`
with every `raise typer.Exit(1)` replaced by `return 1` and each success path
ending in `return 0`. The typer command keeps its options and does:

```python
    code = run(manifest, dry_run=dry_run, source_dir=source_dir, vision=vision)
    if code:
        raise typer.Exit(code)
```

- [x] Step 1: apply the five refactors
- [x] Step 2: `uv run pytest tests/unit/ -q` - expect 383 passed, unmodified
      test files
- [x] Step 3: spot-check the CLI surfaces still exit correctly:
      `uv run python tools/check_invariants.py; echo $status` (0),
      `uv run python tools/check_docs.py >/dev/null; echo $status` (0)
- [x] Step 4: commit `refactor(tools): callable run() seams for preflight/wait_ready/check_*`

### Task 3: convert tasks.py subprocess hops to calls

Add to the tools import block (aliases avoid shadowing by the `status` /
`scenario_status` command functions defined later in the file):

```python
import check_docs
import check_invariants
import check_topics
import e2e_report
import e2e_status as e2e_status_tool
import preflight
import scenario_status as scenario_status_tool
import status as status_tool
import wait_ready
```

Then, preserving every print and exit code exactly:

1. `sim()` preflight block becomes:

```python
    if not preflight.run("headless"):
        print("Preflight failed. Aborting launch.", file=sys.stderr)
        raise typer.Exit(int(ExitCode.PRECONDITION))
```

2. `sim()` wait block: replace the `subprocess.run([... wait_ready ...])` +
   `res.returncode != 0` with:

```python
    ready = wait_ready.wait(timeout)
    elapsed = _time.monotonic() - started
    if not ready:
```

   (rest of the NOT READY branch unchanged).

3. `hw()`: same two conversions with `preflight.run("hw")` and its existing
   "Aborting hardware launch." message.

4. `test e2e` preflight: `if not preflight.run("gui"):` (the old subprocess
   passed no `--mode`, whose default is `"gui"`), keep the existing message +
   `PRECONDITION` exit.

5. `_run_e2e_sim_group`: replace the wait_ready `try/except CalledProcessError`
   with `if not wait_ready.wait(180):` followed by the existing `[FAIL] sim
   never became ready` branch (failure-report JSON writes and
   `return len(scenarios)` unchanged). Replace the topic-audit subprocess with:

```python
        if audit_topics:
            print("Auditing topic graph...")
            if check_topics.run(Path("docs/TOPICS.md")) != 0:
                print("  [FAIL] topic graph violates docs/TOPICS.md", file=sys.stderr)
                fails += 1
```

6. `_e2e_run` report generation:

```python
        print("Generating E2E Report...")
        block, report_code = e2e_report.build_block(LOG_DIR)
        print(block)

        if fails > 0 or report_code != 0:
```

7. `e2e_status_cmd`:

```python
@app.command("e2e-status")
def e2e_status_cmd() -> None:
    """Print progress/verdict of the current or last e2e run (poll while detached)."""
    text, code = e2e_status_tool.build_status(
        LOG_DIR, e2e_status_tool._pid_alive(LOG_DIR / "e2e.pid")
    )
    print(text)
    raise typer.Exit(code)
```

8. `status()`:

```python
@app.command()
def status():
    """View workspace status snapshot (nodes, live status, capabilities)."""
    status_tool.main()
```

9. `scenario_status()`:

```python
    line, code = scenario_status_tool.format_scenario_status(LOG_DIR, name or None)
    print(line)
    raise typer.Exit(code)
```

10. `topics()`:

```python
    raise typer.Exit(check_topics.run(Path("docs/TOPICS.md"), vision=vision))
```

    NOTE: the old `topics()` ignored the subprocess returncode (always exited
    0). `just log topics` exiting nonzero on a manifest violation matches the
    documented contract (AGENTS.md verify table) and the e2e audit path; this
    is the one deliberate exit-code correction in the plan. Record it in the
    commit message.

11. `check()` invariants + docs steps:

```python
    print("Checking branch invariants...")
    if not check_invariants.run():
        failed_steps.append("branch invariants")

    print("Checking agent docs identifiers...")
    if check_docs.run(ROOT) != 0:
        failed_steps.append("docs identifiers")
```

- [x] Step 1: apply all conversions
- [x] Step 2: `rg "uv.*run.*python.*tools/" tasks.py` - expected remaining
      hits: ONLY the `log_capture.py` pipeline string in
      `_ros2_launch_capture_argv` (a stdin filter, stays a subprocess)
- [x] Step 3: `just check` - all pass (this exercises check_invariants.run +
      check_docs.run in-process)
- [x] Step 4: commit `refactor(tasks): call tools in-process instead of uv-run subprocess hops`

### Task 4: live verification gate

- [x] `just sim` - expect `READY: /fmu topics up, rosbridge:9090, GCS params
      committed, recording: off (use --record) - <N>s (logs/latest.log)`;
      note N (baseline was ~14-17s; expect equal or slightly faster)
- [x] `just status` - `stack: UP (...)` with node list
- [x] `just log topics` - all `[OK]`, exit 0
- [x] `just scenario-status` and `just e2e-status` print sensibly (exit 2 for
      e2e-status if no run exists - unchanged contract)
- [x] `just stop` - `STOPPED: ... 0 survivors`, exit 0
- [x] `just scenario 01_arm_takeoff` - PASS
- [x] `just test e2e` - all 8 scenarios PASS, exit 0
- [x] `just sim --overlay bogus` - usage error exit 2 (bootstrap/validation
      path unchanged)
- [x] commit any fixups; update `plans/README.md` row

## STOP conditions

- `uv run tasks.py --help` fails after Task 1 (project env missing a dep the
  script env had): STOP, report the import error. Do not add deps to fix it
  silently.
- Any verdict line or exit code differs from the pre-change behavior in
  Task 4 (compare against a `git stash` run if unsure): STOP.
- `wait_ready.wait()` in-process behaves differently from the subprocess
  (e.g. websocket import state, signal handling during the poll loop): STOP
  and report; the subprocess form is the fallback.

## Explicitly out of scope

- The `justfile` double-sourcing (`_run` sources ROS+workspace AND
  `_bootstrap` re-sources): the in-Python `_source_workspace_env` is
  load-bearing for the post-`_build_workspace` re-source (its cache keys on
  `install/setup.bash` mtime). Leave it.
- Scenario scripts, the e2e worker Popen, colcon/ruff/ty/pytest/ros2/skein
  subprocesses: process boundaries stay.
- `tools/gcs_heartbeat.py`, `tools/log_capture.py`: launched by the launch
  stack, not tasks.py.
