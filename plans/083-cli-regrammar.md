# Plan 083: CLI regrammar - noun-verb surface, content-first bare `just`, docs + harness contract

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in "STOP conditions" occurs, stop and report - do not
> improvise. When done, update this plan's row in `plans/README.md`.
>
> **Drift check (run first)**: plans 081 AND 082 MUST have landed. Confirm:
> - `rg "wait_app|def runs\(|log_view" tasks.py` hits (082 landed).
> - `rg "run_supervisor.supervise" tasks.py` hits (081 landed).
> - `just --list` still shows `scenario`, `scenario-status`, `e2e-status`,
>   `status`, `test` (this plan deletes/reshapes them). If some are already
>   gone: reconcile - the deletions below may be partially done.

## Status

- **Priority**: P1
- **Effort**: M/L
- **Risk**: MED (touches every documented command name; no runtime logic
  changes - bodies move, they do not change; pinned by check_docs, unit
  tests, and a full live e2e)
- **Depends on**: 081, 082 (hard); 080 independent but land it first so one
  final e2e gates everything
- **Category**: agent-first CLI redesign (spec: `plans/079-agent-first-cli-design.md`)
- **Planned at**: commit `82c21d0`, 2026-07-17

## Why this matters

The approved surface (spec section "Command surface"): noun-verb grammar,
content-first bare `just`, and the deletions that 081/082 made safe:
`wait run` + `runs` subsume `e2e-status` + `scenario-status`; `run`/`e2e`
subsume `scenario`/`test e2e`. The spec's harness contract ("every command
is bounded"; Claude Code `run_in_background` fast path; portable
detach+wait path) gets written into AGENTS.md, and the doc-drift net
(`check_docs`) learns the new grammar so it cannot rot.

Target surface (unchanged commands not listed): `just sim start [flags]`,
`just hw start [flags]`, `just stop`, `just run <name> [--detach]`,
`just e2e [--detach]`, `just runs`, `just wait ready|run [--timeout N]`,
`just log since|events|summary|topics|tail`, `just test` (unit only),
bare `just` = status snapshot + next actions.
Deleted: `just scenario`, `just scenario-status`, `just e2e-status`,
`just test e2e`, `just test scenario`, `just status`, bare `just sim`.

## Tasks

### Task 1: tasks.py regrammar (bodies move verbatim)

**Files**: modify `tasks.py`; test `tests/unit/` (retarget any test that
imports renamed commands - `rg "from tasks import|import tasks" tests/unit/`).

- [ ] Step 1: `sim` becomes a sub-app; `hw` likewise. The existing `sim()`
      function body moves UNCHANGED under `sim_app.command("start")`; same
      for `hw()`:

```python
sim_app = typer.Typer(help="Simulation stack lifecycle.")
app.add_typer(sim_app, name="sim")

@sim_app.command("start")
def sim_start(
    ... exact current sim() signature: gui, world, model, vision, overlay,
    record, build/--no-build, timeout ...
):
    """Boot the sim stack detached, wait until ready, print a verdict, return."""
    ... current sim() body, verbatim ...
```

`stop` stays top-level (one teardown for both nouns; docstring: "Exhaustive
cold teardown of sim or hardware stack").

- [ ] Step 2: `run` replaces `scenario`: rename the `scenario()` command to
      `run` (function `run_cmd` to avoid shadowing, registered as
      `@app.command("run")`), body unchanged, plus a `--detach` flag ONLY if
      it already exists; if not, do NOT add one here (single runs are
      bounded by the 081 supervisor; detach is e2e's contract). Add
      `--timeout` threading to the supervisor call:

```python
@app.command("run")
def run_cmd(
    name: str = typer.Argument(..., help="Scenario name, e.g. 01_arm_takeoff"),
    timeout: int = typer.Option(300, "--timeout", help="Supervisor hard deadline (s)."),
):
    """Run one scenario under the run supervisor (bounded; always leaves a run record)."""
    ... current scenario() body; pass deadline_s=timeout down via
    _run_e2e_sim_group(...) - add a deadline_s: float = 300.0 keyword to
    _run_e2e_sim_group and thread it to run_supervisor.supervise ...
```

- [ ] Step 3: `e2e` replaces `test e2e`: new top-level command whose body is
      the current `test()` e2e branch verbatim (including `--detach` and the
      deprecated `--wait` no-op); `test()` shrinks to the unit-test branch
      only (drop its `type` argument entirely; docstring "Run unit tests").
      Keep the hidden `e2e-worker` command as is.
- [ ] Step 4: deletions: remove `scenario_status` (`scenario-status`),
      `e2e_status_cmd` (`e2e-status`), and the top-level `status()` command
      registration - but KEEP `status_tool` importable (Task 2 uses it).
      `reports.build_status` stays (wait run's e2e branch uses it);
      `reports.format_scenario_status` is now uncalled from tasks.py -
      delete it AND its tests in `tests/unit/test_reports.py` (the verdict
      line lives on in run records via `runs`).
- [ ] Step 5: hint-string sweep: user-facing strings written by 081/082 that
      name old commands must follow the rename -
      `rg '"[^"]*just (scenario|test e2e|e2e-status|scenario-status)' tasks.py tools/`
      and update each (known: `format_runs`'s empty-state line in
      `tools/run_supervisor.py` says `just scenario <name>` -> `just run
      <name>`; the no-declared-config message in the old `scenario()` body).
- [ ] Step 6: `just check` passes; `uv run tasks.py sim start --help`,
      `run --help`, `e2e --help`, `wait --help` all render.
- [ ] Step 7: commit `refactor(cli)!: noun-verb regrammar - sim/hw start, run, e2e; drop status trio`

### Task 2: content-first bare `just`

**Files**: modify `justfile`, `tasks.py`.

- [ ] Step 1: add a `snapshot` concept to the existing `status` machinery:
      `status_tool.main()` already prints the workspace snapshot; register it
      as a HIDDEN command so the justfile can call it without it being part
      of the documented surface:

```python
@app.command(hidden=True)
def snapshot():
    """Internal: bare-`just` status snapshot."""
    status_tool.main()
    print()
    print("recipes: just --list | logs: just log since | claims: just cap show")
```

- [ ] Step 2: justfile default recipe:

```make
# Default: live status snapshot + where to go next
default:
    @just _run snapshot
```

- [ ] Step 3: justfile recipe table updated to the new surface: recipes
      `sim`, `hw`, `log`, `cap`, `mission`, `wait` all keep the
      `*args` + `_run` forwarding pattern (typer parses the verb); add
      `run`, `runs`, `e2e`; delete `scenario`, `scenario-status`,
      `e2e-status`, `status`, `test`'s comment updated to unit-only. Keep
      `scenario-new`, `analyze`, `gen-markers`, `gen-world`, `setup`,
      `check`, `build`, `clean`, `stop` unchanged. Every recipe keeps a
      one-line `#` comment (that is what `just --list` shows).
- [ ] Step 4: smoke: bare `just` prints the snapshot + hint line (no
      recipe list flood); `just --list` shows the new surface; `just sim
      start --help` reaches typer.
- [ ] Step 5: commit `feat(cli): bare just is a live status snapshot (content-first)`

### Task 3: check_docs learns the new grammar

**Files**: modify `tools/check_docs.py` (`_SUBCOMMANDS`); test
`tests/unit/test_check_docs.py` (update any pinned dict).

- [ ] Step 1: replace the `_SUBCOMMANDS` dict:

```python
_SUBCOMMANDS = {
    "log": {"summary", "tail", "topics", "since", "events"},
    "cap": {"show", "plan", "record"},
    "mission": {"list", "validate", "show", "sim", "schema"},
    "wait": {"ready", "run"},
    "sim": {"start"},
    "hw": {"start"},
}
```

(`test` loses its entry: it has no subcommands now, so `just test` validates
as a plain recipe.)

- [ ] Step 2: `uv run pytest tests/unit/test_check_docs.py -q` passes.
- [ ] Step 3: commit `chore(docs-check): subcommand map matches the regrammar`

### Task 4: AGENTS.md + README + docs sweep

**Files**: modify `AGENTS.md`, `README.md`; sweep `docs/*.md`.

- [ ] Step 1: find every stale command reference:
      `rg -l "just scenario |just scenario-status|just e2e-status|just test e2e|just status|just sim( |\`)" AGENTS.md README.md docs/`
      and update each to the new surface. AGENTS.md sections to rewrite:
      Tooling table, Common workflows table, Verify table, Command verdicts
      section, Logs workflow (add `just log since` as step 0 of the agent
      query workflow), If-X-fails table.
- [ ] Step 2: add a short new AGENTS.md section after "Command verdicts and
      exit codes":

```markdown
## Harness contract (bounded commands)

Every command is bounded: launches wait-with-timeout, runs execute under a
supervisor (hard deadline + log-silence watchdog, verdict file always
written), waits take `--timeout` and exit 3 with a progress snapshot when
still running. The only intentionally unbounded command is `just log tail`
(human-only). Verdicts: `PASS` / `FAIL` (flew, missed criteria - read the
mission events) / `STUCK` (stack or harness wedged - read the stack log).

| Driving agent | Long-running workflow |
|---------------|----------------------|
| Claude Code | Launch `just run <name>` or `just e2e` as a background task; the harness re-invokes you when the verdict lands. No polling. |
| Any harness | `just e2e --detach`, then repeated `just wait run --timeout 120`; each timeout prints progress and exits 3. |
```

- [ ] Step 3: README quick-start / everyday-commands tables updated to
      `just sim start`, `just run <name>`, `just e2e`, `just wait run`,
      `just runs`, `just log since`.
- [ ] Step 4: `just check` passes - check_docs is the gate that every
      backticked `just ...` token in the rewritten docs actually exists.
- [ ] Step 5: commit `docs: regrammared command surface + harness contract`

### Task 5: final live gate (operator)

- [ ] `just sim start` -> READY verdict; bare `just` shows the live stack;
      `just stop`.
- [ ] `just run 01_arm_takeoff` PASS; `just runs` lists it.
- [ ] `just e2e --detach`; `just wait run --timeout 30` exits 3 with
      heartbeat; `just wait run --timeout 600` exits 0 with the aggregate
      block; `just e2e` (blocking form) not needed if the detached cycle
      passed 8/8.
- [ ] `just check` green; `rg "e2e-status|scenario-status" AGENTS.md README.md docs/ justfile tasks.py` -> no hits
      (plans/ and docs/superpowers/ excluded - history keeps old names).
- [ ] Update `plans/README.md` row. Record the surface delta in the final
      commit message (recipes before/after count).

## STOP conditions

- Any moved body needing a LOGIC change to fit its new home: STOP - this
  plan moves bodies verbatim; logic changes belong in their own plan.
- `just check`'s check_docs step failing on a doc token you believe correct:
  fix the `_SUBCOMMANDS` map or the doc, never the checker's logic.
- Evidence/claims flow (`just cap ...`) affected in any way: STOP -
  cap/mission are explicitly unchanged in the spec.
- The `justfile` `_run` forwarding or distrobox delegation needing changes:
  STOP (it is deliberately untouched; see plans/README.md Round 4b policy).

## Explicitly out of scope

- Renaming `scenario-new` (kept; creation tooling, not runtime surface).
- `analyze`, `gen-markers`, `gen-world`, `setup`, `check`, `build`, `clean`:
  unchanged.
- Old-name aliases or deprecation shims: the repo predates external users;
  docs are the contract and they are rewritten atomically here (exception:
  `e2e --wait` no-op alias survives, it is already documented as deprecated).
- Memory/plan-file archaeology: historical plans keep the old names.
