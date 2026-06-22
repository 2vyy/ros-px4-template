# Plan 012: Fix `just` arg forwarding so `analyze --query '<expr>'` survives shell metacharacters

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving on. Touch
> only the files listed as in scope. If any STOP condition occurs, stop and
> report — do not improvise. When done, update the status row for this plan in
> `plans/README.md` — unless a reviewer dispatched you and told you they maintain
> the index.
>
> **Drift check (run first)**: `git diff --stat f0dea37..HEAD -- justfile`
> If `justfile` changed since this plan was written, compare the "Current state"
> block below against the live file before proceeding; on a mismatch, STOP.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: MED (edits `_run`, the universal recipe plumbing every `just` workflow routes through — a regression breaks `sim`/`stop`/`analyze`/`log`/etc.)
- **Depends on**: none (independent; improves plan 011's `analyze`)
- **Category**: bug / dx
- **Planned at**: commit `f0dea37`, 2026-06-22

## Why this matters

`just analyze latest --query 'z < -1' --stats` fails with
`bash: line 1: -1: No such file or directory`. The predicate `z < -1` is a skein
`--where` expression, but `just` forwards recipe args by interpolating `{{args}}`
**space-joined without re-quoting**, so by the time the string hits `bash -ec`,
the `<` is parsed as a redirect and `-1` as a filename. This was found during the
live SITL verification of plan 011 (the workaround was calling `skein query
--where 'z < -1'` directly, which works). It makes the documented
`just analyze --query …` path unusable for any realistic predicate (predicates
contain `<`/`>` and spaces by nature).

The fix is the canonical `just` idiom: enable `set positional-arguments` and
forward args as real shell positional parameters (`"$@"`) instead of the
unquoted `{{args}}` string — at **every** hop, including the distrobox re-entry.
This also hardens every other variadic recipe (`sim`, `hw`, `test`, `cap`, `log`)
against args containing spaces/metacharacters.

## Current state

`justfile` today (verbatim — the whole file, since this plan rewrites most of it):

```just
# px4-ros-template task runner — run `just --list`
set shell := ["bash", "-ec"]
set dotenv-load := true
ROS_SETUP := env_var_or_default("ROS_SETUP", "/opt/ros/jazzy/setup.bash")
WS_INSTALL := justfile_directory() / "install/setup.bash"

# Default recipe: list all workflows
default:
    @just --list

# Sourced environment executor (auto-delegates to Distrobox if ROS is missing on host)
_run *args:
    @if [ ! -f "{{ROS_SETUP}}" ] && command -v distrobox >/dev/null 2>&1; then \
        distrobox enter ubuntu -- bash -lc "cd {{justfile_directory()}} && just _run {{args}}"; \
    else \
        source {{ROS_SETUP}} && \
        (source {{WS_INSTALL}} 2>/dev/null || true) && \
        unset VIRTUAL_ENV && \
        uv run tasks.py {{args}}; \
    fi

# One-time workspace setup (auto-detects PX4 version, runs uv sync and rosdep)
setup:
    @just _run setup

# Complete quality gate (auto-formats, auto-fixes lints, typechecks, compiles workspace, and runs unit tests)
check:
    @just _run check

# Boot the sim stack detached, wait until ready, print a verdict, and return
sim *args:
    @just _run sim {{args}}

# Exhaustive cold teardown of the whole stack (no process survives)
stop:
    @just _run stop

# Analyze a recorded run with skein (overlay bag+ULog; optional --query)
analyze *args:
    @just _run analyze {{args}}

# Connect to serial hardware flight controller
hw *args:
    @just _run hw {{args}}

# Verification suite (unit tests, live scenario <name>, or e2e headless cycles)
test *args:
    @just _run test {{args}}

# Run a specific scenario test directly by name (e.g. just scenario 01_arm_takeoff)
scenario name:
    @just _run scenario {{name}}

# View JSON workspace status snapshot (nodes, live status, capabilities)
status:
    @just _run status

# Manage verified capabilities registry (show, mark)
cap *args:
    @just _run cap {{args}}

# Observability hub (merge logs, watch/tail logs, or validate live topic graph)
log *args:
    @just _run log {{args}}
```

Why each hop loses quoting:
- `analyze *args` body `@just _run analyze {{args}}` — `{{args}}` expands
  space-joined and unquoted, so `--query 'z < -1'` becomes `--query z < -1` in
  the recipe's `bash -ec` shell → redirect. **This is the first and fatal hop.**
- `_run` then re-forwards `{{args}}` again (and the distrobox branch re-invokes
  `just _run {{args}}` inside a `bash -lc "…"` string — a second loss).

Key facts about the environment (so you don't have to rediscover them):
- The host has **no** ROS (`/opt/ros/jazzy/setup.bash` absent), so `_run` always
  takes the **distrobox** branch on the host; inside the `ubuntu` container ROS is
  present, so the re-invoked `_run` takes the **else** branch. Both branches must
  forward args correctly.
- `distrobox enter <name> -- <cmd> <args...>` passes argv through to the container
  without a shell in between, so args given as separate `bash -lc` positional
  parameters survive without string re-quoting.
- `bash -lc 'SCRIPT' ARG0 ARG1 ARG2 …` sets `$0=ARG0`, `$1=ARG1`, … inside
  SCRIPT. This is the robust way to pass args through `bash -lc` (no `printf %q`).

## Commands you will need

| Purpose                | Command                                              | Expected on success                       |
|------------------------|------------------------------------------------------|-------------------------------------------|
| Parse + list recipes   | `just --list`                                        | exit 0; lists default/setup/check/sim/stop/analyze/hw/test/scenario/status/cap/log |
| Evaluate variables     | `just --evaluate`                                    | exit 0 (justfile parses)                  |
| Quoting technique check| see Step 3                                           | prints the args intact                    |
| Unit suite (unaffected, sanity) | `uv run pytest tests/unit/ -q --ignore=tests/unit/test_scenario_verdict.py` | all pass |

`just` here supports `set positional-arguments` (it already uses `set
dotenv-load`). If `just --list` reports an unknown-setting error after Step 1,
that is a STOP condition.

## Scope

**In scope** (only files to modify):
- `justfile`
- `plans/README.md` (status row)

**Out of scope** (do NOT touch):
- `tasks.py`, `tools/`, any Python — the fix is entirely in the justfile. The
  `analyze` typer command already works; only the shell forwarding is broken.
- The `_run` distrobox container name (`ubuntu`) and the ROS sourcing logic — keep
  them exactly as-is; only change how **args** are forwarded.
- Adding new recipes or changing recipe behavior beyond arg forwarding.

## Git workflow
- Branch: `advisor/012-fix-analyze-query-arg-forwarding`.
- Conventional commit, e.g. `fix(just): forward recipe args via positional params so analyze --query survives < and spaces`.
- Do NOT push or open a PR.

## Steps

### Step 1: Enable `set positional-arguments`

Add the setting directly under `set shell` near the top of `justfile`:

```just
set shell := ["bash", "-ec"]
set positional-arguments
set dotenv-load := true
```

**Verify**: `just --list` → exit 0 and lists the recipes (confirms the setting is
recognized and the file still parses).

### Step 2: Forward args as `"$@"` at every hop

Replace the `_run` recipe and every variadic leaf recipe so args flow as shell
positional parameters. The **target** recipes (replace the current ones exactly):

```just
# Sourced environment executor (auto-delegates to Distrobox if ROS is missing on host)
_run *args:
    @if [ ! -f "{{ROS_SETUP}}" ] && command -v distrobox >/dev/null 2>&1; then \
        distrobox enter ubuntu -- bash -lc 'cd "$1" && shift && exec just _run "$@"' _ "{{justfile_directory()}}" "$@"; \
    else \
        source {{ROS_SETUP}} && \
        (source {{WS_INSTALL}} 2>/dev/null || true) && \
        unset VIRTUAL_ENV && \
        uv run tasks.py "$@"; \
    fi
```

Leaf recipes — change `{{args}}` → `"$@"` (keep comments/signatures):

```just
sim *args:
    @just _run sim "$@"

analyze *args:
    @just _run analyze "$@"

hw *args:
    @just _run hw "$@"

test *args:
    @just _run test "$@"

cap *args:
    @just _run cap "$@"

log *args:
    @just _run log "$@"
```

And the single-arg `scenario` recipe — quote the interpolation so a name with
spaces survives:

```just
scenario name:
    @just _run scenario "{{name}}"
```

Leave `setup`, `check`, `stop`, `status`, `default` unchanged (they forward no
args).

How the distrobox line works (so you reproduce it correctly): the host `_run`
runs `distrobox enter ubuntu -- bash -lc 'cd "$1" && shift && exec just _run
"$@"' _ "<justfile_dir>" "$@"`. Here `_` is `$0`, `<justfile_dir>` is `$1`, and
the recipe's own args (`"$@"`, e.g. `analyze latest --query 'z < -1' --stats`)
become `$2…`. The script `cd`s into the dir, `shift`s off the dir, then
`exec just _run "$@"` re-runs `_run` inside the container with the args intact as
separate parameters — no string re-quoting. Inside the container ROS is present,
so that `_run` takes the `else` branch and runs `uv run tasks.py "$@"`.

**Verify**: `just --list` → exit 0 (still parses).

### Step 3: Confirm the quoting technique preserves args (no ROS needed)

This isolates the core mechanism the distrobox branch relies on, proving args
with `<` and spaces survive `bash -lc` positional passing:

```bash
bash -lc 'cd "$1" && shift && printf "[%s]\n" "$@"' _ /tmp latest --query 'z < -1' --stats
```

**Verify**: prints exactly:
```
[latest]
[--query]
[z < -1]
[--stats]
```
i.e. `z < -1` stays one intact argument. (If it splits or errors, the technique
is wrong — STOP and report.)

### Step 4: Sanity-check the unit suite is unaffected

The change is justfile-only, but confirm nothing else regressed:

**Verify**: `uv run pytest tests/unit/ -q --ignore=tests/unit/test_scenario_verdict.py`
→ all pass.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `grep -n "set positional-arguments" justfile` matches.
- [ ] `grep -n "{{args}}" justfile` returns **nothing** (every variadic recipe forwards `"$@"`).
- [ ] `grep -n 'uv run tasks.py "\$@"' justfile` matches (the else branch forwards positionally).
- [ ] `grep -n "printf '%q'" justfile` returns nothing (we use positional passing, not requoting).
- [ ] `just --list` exits 0 and lists all 11 recipes + default.
- [ ] Step 3's quoting check prints `z < -1` as a single `[z < -1]` line.
- [ ] `uv run pytest tests/unit/ -q --ignore=tests/unit/test_scenario_verdict.py` passes.
- [ ] Only `justfile` (and, by the reviewer, `plans/README.md`) changed (`git status`).
- [ ] `plans/README.md` status row updated.

Live (distrobox) verification — the reviewer performs this (you cannot, no
distrobox here); do **not** fake it. Listed so the reviewer knows the target:
- [ ] `just analyze latest --query 'z < -1' --stats` runs the skein query (no
      `bash: -1: No such file` error) and prints query output.
- [ ] Regression: `just status` still works (cheap `_run` path), and a fresh
      `just sim` → `just stop` still boots and tears down cleanly (the heavy
      distrobox `_run` path).

## STOP conditions

Stop and report back (do not improvise) if:
- `just --list` errors on `set positional-arguments` (this `just` version doesn't
  support it) — report the version (`just --version`); do not hack around it.
- Step 3's quoting check does not print `z < -1` as one intact argument.
- The `justfile` "Current state" block doesn't match the live file (drift).
- The fix appears to need touching `tasks.py` or any Python.
- A verification fails twice after a reasonable fix attempt.

## Maintenance notes

- `set positional-arguments` makes `$@`/`$1`… available in every recipe and is the
  reason `"$@"` works; do not remove it while any recipe forwards `"$@"`.
- The distrobox branch passes args as `bash -lc` positional parameters (`_ "$1"
  "$@"` pattern) rather than building a command string — this is deliberately
  robust against spaces/`<`/`>`/`$`. If someone "simplifies" it back to
  `just _run {{args}}` or a `"$@"` interpolated into a quoted string, the bug
  returns.
- Reviewer focus: confirm no `{{args}}` remain; confirm the live `just sim`/`stop`
  path still works (the distrobox `_run` change is the real risk, not the
  `analyze` fix itself); confirm `just analyze --query 'z < -1'` now works.
- Follow-up still open from the 011 live run: skein `.venv` thrash across
  host-vs-container Python (harmless, self-correcting) — not addressed here.
