# Plan 045: Bring `tasks.py` under the quality gate it enforces

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report - do not improvise. When done, update the status row for this plan
> in `plans/README.md` - unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat ead4cc6..HEAD -- tasks.py`
> Plans 031, 033, 037, and 039 legitimately edit `tasks.py` first - reconcile
> with their diffs (039 rewrites `_source_workspace_env`'s body; this plan
> moves its CALL SITE, the two compose). Any other structural drift vs the
> excerpts is a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MED (changes every command's startup sequencing; gate additions may surface latent errors)
- **Depends on**: none hard. Soft: land AFTER 037 (edits the same ty argv) and
  AFTER 039 (edits `_source_workspace_env`'s body) to avoid merge churn
- **Category**: tech-debt
- **Planned at**: commit `ead4cc6`, 2026-07-06

## Why this matters

`tasks.py` is the largest Python file in the repo (990 lines), orchestrates
every workflow, and is the ONLY Python that `just check` neither lints,
typechecks, nor unit-tests. Every plan since round 2 carries special
instructions to route around this ("verify tasks.py by running commands
directly"). The structural cause is import-time side effects:
`_load_dotenv()` (line 52) and `_source_workspace_env()` (line 70) fire on
`import tasks`, so the module cannot be imported by a test or a typechecker
run without touching the developer's environment. Moving those calls into
the Typer app callback makes the module import-clean, and then adding it to
the ruff/ty invocations in `check` closes the exemption.

## Current state

- `tasks.py:26-34` - module setup: `import typer`, `app = typer.Typer(...)`,
  `ROOT`/`LOG_DIR` constants, a `VIRTUAL_ENV` env cleanup block (keep all of
  this at module level; none of it has side effects beyond `os.environ`).
- `tasks.py:52` - `_load_dotenv()` called at import.
- `tasks.py:70` - `_source_workspace_env()` called at import. (After plan
  039 the body is cached; the call site is unchanged.)
- `tasks.py:390-457` - the `check` command:
  - ruff paths (line 395): `["src/core", "tests", "tools", "sim", "hardware"]`
    - `tasks.py` absent.
  - ty argv (lines 422-429): `["uv", "run", "ty", "check",
    "src/core/ros_px4_template_core/lib", "tests/unit", "tools/",
    "--exclude", "tools/gcs_heartbeat.py"]` - `tasks.py` absent (the
    `--exclude` pair is removed by plan 037; do not re-add it).
  - line 444: `check` also calls `_source_workspace_env()` explicitly on the
    build-skip path - this explicit call is correct and stays.
- `tasks.py` has a PEP 723 inline-metadata block (lines 1-12), so
  `uv run tasks.py` runs it in an isolated script env - the ruff/ty
  subprocesses it spawns run `uv run ruff`/`uv run ty` against the PROJECT
  env (dev group), which is where those tools live. No env change needed.
- `pyproject.toml` `[tool.ty.environment]` has
  `extra-paths = ["src/core", "tools", "tests/scenarios"]`, so ty can resolve
  `tasks.py`'s flat `import bag_recorder`-style imports of `tools/` modules.
- There is a `sys.path` insertion in `tasks.py` (around line 150-160, before
  the flat tool imports) - it stays; it is runtime wiring, not a side effect.
- No file in the repo imports `tasks` as a module today
  (`rg -n "import tasks" --glob '!plans'` -> nothing); the callback change
  cannot break an importer.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Lint tasks.py | `uv run ruff check tasks.py` | exit 0 |
| Typecheck tasks.py | `uv run ty check tasks.py` | exit 0 (after Step 3) |
| Import-cleanliness probe | `uv run python -c "import tasks"` | no output, no env sourcing, exit 0 |
| Every command still works | see Step 4 | unchanged behavior |
| Full gate | `just check` | exit 0, now covering tasks.py |

## Scope

**In scope**:
- `tasks.py` only.

**Out of scope**:
- Splitting `tasks.py` into modules - at this size it is fine; the problem is
  the exemption, not the line count.
- Adding unit tests for `tasks.py` - this plan makes them POSSIBLE
  (import-clean module); writing them is follow-up work.
- `justfile` - unchanged (it still sources ROS before invoking; the
  double-sourcing ownership question is explicitly deferred, see
  `plans/README.md` round-4 notes).
- The PEP 723 block (plan 046 owns dependency-declaration hygiene).

## Git workflow

- Branch: `advisor/045-tasks-under-gate`
- Commit style: `refactor(tasks): import-clean module via app callback; gate tasks.py in check`
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Move the import-time calls into an app callback

Delete the two module-level calls (`_load_dotenv()` at line 52,
`_source_workspace_env()` at line 70 - the function DEFINITIONS stay), and
add directly below `app = typer.Typer(...)`... no - add it after both
function definitions (the callback references them):

```python
@app.callback()
def _bootstrap() -> None:
    """Per-invocation env setup (dotenv + sourced workspace). Runs before every command."""
    _load_dotenv()
    _source_workspace_env()
```

Ordering constraint: `_load_dotenv` must run before `_source_workspace_env`
(the sourced env may depend on `.env`'s `ROS_SETUP`/`PX4_DIR`), same order as
today. Typer/Click runs the callback before the command function and skips it
for bare `--help`, which is a free speedup for `just --list`-adjacent usage.

Check for order-of-definition issues: the callback must be defined AFTER
`_load_dotenv` and `_source_workspace_env`. Everything between the old call
sites and the first `@app.command()` is function/constant definitions, so
moving the calls later cannot change what they see - verify by reading the
module top (lines 1-170): nothing at module level READS the env vars that
dotenv/sourcing set (functions read them at call time).

**Verify**: `uv run python -c "import tasks"` -> exits 0 instantly with no
"Warning: failed to source workspace env" output and no cache-file mtime
change (`ls -l install/.ws_env_cache.json` before/after, if plan 039 landed);
`uv run tasks.py mission list` -> works exactly as before (callback ran).

### Step 2: Add `tasks.py` to the gate

In `check`:

1. ruff paths (line 395): `["src/core", "tests", "tools", "sim", "hardware", "tasks.py"]`.
2. ty argv: append `"tasks.py"` after `"tools/"`.

**Verify**: `uv run ruff check tasks.py` -> exit 0 (fix any findings; they
should be trivial or absent - plans have been running this check manually for
rounds).

### Step 3: Make ty pass on `tasks.py` (annotations only)

Run `uv run ty check tasks.py`. If it reports errors:

- Permitted: type annotations, narrow `# type: ignore[<code>]` comments
  (match the style used in `tools/wait_ready.py`), `TYPE_CHECKING` imports.
- Forbidden: any change to runtime behavior, control flow, or subprocess
  argv construction.

**Verify**: `uv run ty check tasks.py` -> exit 0, and
`git diff tasks.py` beyond Steps 1-2 contains only annotation/comment lines.

### Step 4: Behavior sweep (no sim needed)

Every command family must behave identically. Run:

1. `just --list` -> recipe list.
2. `just mission list` -> mission table.
3. `just cap show` -> capability table.
4. `just log summary` -> summary JSON (or its no-log message).
5. `just scenario-status` -> a verdict or exit 2 with the missing message.
6. `uv run tasks.py sim --timeout 1` on a host WITHOUT a sim environment ->
   fails at preflight with exit 3 (precondition), proving dotenv/sourcing ran
   before the command body needed them.

**Verify**: all six as listed; outputs match a pre-change run (spot-check).

### Step 5: Full gate

**Verify**: `just check` -> exit 0, and its typecheck step output now lists
`tasks.py` among the checked paths.

## Test plan

The Step 4 command sweep is the behavior regression net (repo convention for
`tasks.py`). The import-cleanliness probe is the new property this plan
creates; it is also the enabler for future unit tests. `just check` itself
now covers the file - which is the point.

## Done criteria

- [ ] `rg -n "^_load_dotenv\(\)|^_source_workspace_env\(\)" tasks.py` -> no module-level calls remain
- [ ] `rg -n "@app.callback" tasks.py` -> the `_bootstrap` callback exists
- [ ] `rg -n '"tasks.py"' tasks.py` -> present in both the ruff paths and ty argv of `check`
- [ ] `uv run python -c "import tasks"` -> clean, no sourcing side effects
- [ ] `uv run ty check tasks.py` and `uv run ruff check tasks.py` -> exit 0
- [ ] Step 4 sweep unchanged; `just check` exits 0
- [ ] `git status` shows only `tasks.py` modified
- [ ] `plans/README.md` status row updated (and the round-2 "tasks.py is not
      covered by just check" convention note gets a one-line "closed by 045"
      annotation)

## STOP conditions

- ty reports errors in `tasks.py` that cannot be fixed without behavior
  changes - report the list; the gate addition waits for a human call.
- Any module-level code turns out to READ env vars that dotenv/sourcing set
  (the Step 1 read missed something) - report the line; do not reorder
  definitions to compensate.
- A Step 4 command changes behavior or output - the callback sequencing is
  wrong; revert and report rather than patching per-command.

## Maintenance notes

- Follow-up (not this plan): with `import tasks` now clean, the failure-path
  wiring (plan 033's `_print_failure_digest` call sites, exit-code mapping)
  becomes unit-testable with `typer.testing.CliRunner` - the same pattern
  `tests/unit/test_wait_ready.py` uses.
- Reviewer: confirm the callback is registered on `app` (not a sub-Typer like
  `cap_app`), or `just cap show` would skip bootstrap.
