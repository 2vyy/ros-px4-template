# Plan 017: README command examples match the real `just` interface

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving on. If
> anything in "STOP conditions" occurs, stop and report. When done, update this
> plan's row in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 0f93f0e..HEAD -- README.md justfile tasks.py`
> If any changed, compare the "Current state" excerpts to the live files before
> proceeding; on a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none (coordinate with 015, which edits a different README section)
- **Category**: docs
- **Planned at**: commit `0f93f0e`, 2026-06-22

## Why this matters

The README is the front door. Its command examples drifted from the real CLI:
they show `just sim stop`, `just sim gui`, and `just sim bg`, but the actual
interface is detach-always `just sim [--gui]` plus a **separate** `just stop`
recipe. A new user who copy-pastes the very first commands they see (`just sim
stop` to stop, `just sim gui` to get a GUI) gets a usage error, because `just
sim` forwards its args to `tasks.py sim` which has no `stop`/`gui`/`bg`
subcommand. Fixing five lines removes a guaranteed first-five-minutes failure.

## Current state

The real interface (authoritative):
- `justfile:32-33`:
  ```
  sim *args:
      @just _run sim "$@"
  ```
  `just sim` forwards flags to `tasks.py sim`. The flags are `--gui`, `--world`,
  `--model`, `--vision`, `--speed`, `--overlay`, `--no-build`, `--timeout`
  (see `tasks.py:459` `def sim(...)` and `AGENTS.md`). `just sim` **always
  detaches** and returns after a readiness verdict — there is no foreground vs
  `bg` distinction.
- `justfile:36-37`:
  ```
  stop:
      @just _run stop
  ```
  Teardown is its own recipe: `just stop`.

The drifted README text:
- `README.md:90-94` (Quick start, "Stop everything"):
  ```
  1. Stop everything:

  ```bash
  just sim stop
  ```
  ```
- `README.md:129-141` (Everyday commands):
  ```
  just                              # list all workflows
  just setup                        # one-time setup (px4_msgs, uv, rosdep, build)
  just check                        # format, lint, typecheck, build, unit tests
  just sim                          # start headless sim (foreground)
  just sim gui                      # start sim with Gazebo GUI
  just sim bg                       # start headless sim in background and wait until ready
  just status                       # JSON status snapshot of running sim
  just scenario <name>              # live scenario (e.g. 01_arm_takeoff)
  just log summary                  # regenerate latest_summary.json
  just log topics                   # audit live topics vs docs/TOPICS.md
  just analyze                      # overlay+query the latest recorded run via skein
  ```
  Three lines are wrong: `just sim` is **not** foreground, `just sim gui` should
  be `just sim --gui`, and `just sim bg` does not exist (sim is always
  backgrounded). There is also no `just stop` line, which should exist.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Confirm real recipes | `grep -nA1 "^sim\|^stop:" justfile` | shows `sim *args` and `stop:` |
| Confirm no `bg`/`gui` subcommand | `grep -n "\"gui\"\|\"bg\"\|\"stop\"" tasks.py` | no sim-subcommand match |
| Re-grep README after edit | `grep -n "just sim" README.md` | only the corrected lines |

(All read-only; no ROS/build needed.)

## Scope

**In scope**:
- `README.md` — only the "Stop everything" quick-start block (lines ~90-94) and
  the "Everyday commands" fenced block (lines ~129-141).

**Out of scope** (do NOT touch):
- The `README.md` project-structure table (lines ~99-125) — plan 015 owns it.
- `justfile`, `tasks.py`, `AGENTS.md` — the interface is correct; only the README
  is wrong.

## Git workflow

- Branch: `advisor/017-fix-readme-command-drift`
- Commit style: conventional (e.g. `docs: fix README command examples to match the real just interface`).
- Do NOT push or open a PR unless instructed.

## Steps

### Step 1: Fix the "Stop everything" quick-start block

In `README.md`, change the fenced block at lines 92-94 from:
```bash
just sim stop
```
to:
```bash
just stop
```

**Verify**: `grep -n "just sim stop" README.md` → no output.

### Step 2: Fix the "Everyday commands" block

Replace the three sim lines and add a `just stop` line. Change:
```
just sim                          # start headless sim (foreground)
just sim gui                      # start sim with Gazebo GUI
just sim bg                       # start headless sim in background and wait until ready
```
to:
```
just sim                          # boot headless sim detached, wait until ready, return
just sim --gui                    # same, with the Gazebo GUI
just stop                         # exhaustive cold teardown of the whole stack
```

Leave the surrounding lines (`just`, `just setup`, `just check`, `just status`,
`just scenario`, `just log ...`, `just analyze`) unchanged.

**Verify**: `grep -n "just sim\|just stop" README.md` → shows `just sim`,
`just sim --gui`, and `just stop`; shows **no** `just sim gui`, `just sim bg`,
or `just sim stop`.

## Test plan

Docs-only; no automated tests. Verification is the greps above. Optionally
cross-check each documented command against `AGENTS.md` "Common just workflows"
table to confirm naming consistency.

## Done criteria

ALL must hold:

- [ ] `grep -n "just sim stop\|just sim gui\|just sim bg" README.md` returns nothing
- [ ] `grep -n "just stop" README.md` returns at least one line
- [ ] `grep -n "just sim --gui" README.md` returns one line
- [ ] No files other than `README.md` modified (`git status --porcelain`)
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report if:

- The README excerpts at lines 90-94 or 129-141 do not match "Current state"
  (the file drifted — likely plan 015 already restructured nearby; re-locate the
  exact lines before editing, and if they were already corrected, mark this plan
  REJECTED with that note).
- `grep` reveals `just sim` actually does accept a `stop`/`gui`/`bg` subcommand
  in `tasks.py` (the interface, not the docs, is what changed) — then the docs
  may be right and this plan is moot.

## Maintenance notes

- `AGENTS.md` already documents the correct flags; if the sim flag set changes,
  update both `AGENTS.md` and this README block together.
- Reviewer: confirm every command shown in the README "Everyday commands" block
  exists as a `just` recipe or a documented flag.
