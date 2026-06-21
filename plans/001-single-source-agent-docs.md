# Plan 001: Agent-facing docs are a single, accurate source of truth

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 5175284..HEAD -- README.md AGENTS.md docs/MCP.md CLAUDE.md`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: docs / dx
- **Planned at**: commit `5175284`, 2026-06-20

## Why this matters

This repo is driven by a CLI agent that loads `CLAUDE.md` as its operating
instructions every session. Today `CLAUDE.md` is an **untracked, frozen copy of
`AGENTS.md`** that has drifted: it documents the *old* CLI (`just sim [mode]`
with `bg/stop/kill`, `just log merge`, a `bridges/` directory). The maintainer
updated `AGENTS.md` but not the copy the agent actually reads. On top of that,
`AGENTS.md` and `README.md` still contain individually-wrong facts that point
agents at files and commands that no longer exist. Wrong instructions are more
expensive than missing ones: an agent that follows them builds the wrong thing.
After this plan, `CLAUDE.md` can never drift from `AGENTS.md` (it becomes a
symlink), and both `AGENTS.md` and `README.md` describe the code as it is.

## Current state

Three files, all hand-maintained, overlapping and drifted:

- `CLAUDE.md` — **untracked** (shows as `??` in `git status`), 10.8K, a stale
  byte copy of an older `AGENTS.md`. This is the file Claude Code loads as
  project instructions. `diff CLAUDE.md AGENTS.md` reports +93/-79 lines.
- `AGENTS.md` — the live operating guide (tracked, recently updated). Still
  contains these wrong facts:
  - Line 9: `Complete README quick start (through \`just sim\` or \`just hardware\`)`
    — there is no `just hardware` recipe; it is `just hw` (see `justfile:39`).
  - Line 28, invariant #5: ``5. Pure logic in `lib/`, nodes in `nodes/`, PX4 specific glue in `bridges/`.``
    — there is **no `bridges/` directory**. `ls src/core/ros_px4_template_core/`
    shows only `lib/` and `nodes/`. The PX4/NED conversion lives in
    `nodes/offboard_controller.py` and `nodes/mission_manager.py`.
  - Line 149: ``- New mission phases go in `lib/mission_runtime.py` (add a `PHASE_*` constant and a branch in `tick`). Do not embed phase logic in `nodes/mission_manager.py`.``
    — there is **no `lib/mission_runtime.py`** and no `PHASE_*`/`tick` if-elif.
    Missions are now data-driven: `nodes/mission_manager.py:32-36` imports from
    `ros_px4_template_core.lib.mission.{commands,detection,engine,loader,types}`.
    Behaviors/guards are registered in `lib/mission/registry.py`; missions are
    YAML state graphs loaded by `lib/mission/loader.py`.
- `README.md` — project overview, with stale facts:
  - Line 21: ``Live topics are checked ... with `just check-topics` ...`` — the
    recipe is `just log topics` (see `justfile:59` + `tasks.py:809-815`).
  - Line 22: ``Each node writes logs to `logs/<node>.jsonl`. After a run, `just log merge` produces ... `logs/latest.log`, `logs/latest.jsonl`, and a summary ...`` —
    wrong. Logging was redesigned to a **single logfmt `logs/latest.log`** for
    all processes; the regenerate command is `just log summary` (see
    `AGENTS.md:107-115` for the accurate description). There are no per-node
    `*.jsonl` files and no `just log merge`.
  - Line 102: ``# Core nodes, lib, bridges (sim/hardware agnostic)`` — no `bridges`.
  - Line 104: ``# frame_transforms, mission_runtime, StructuredLogger`` — the
    files are `frames.py` and the `mission/` package (engine), not
    `frame_transforms`/`mission_runtime`.
  - Line 106: ``│   ├── px4_ros_sim/   # Sim-only ROS helpers (not imported from core)`` —
    **there is no `src/px4_ros_sim/`** (`git ls-files src/` confirms only
    `core/`, `px4_ros_msgs/`, and the cloned `px4_msgs/`).
  - Line 119: ``# capabilities CLI, log merger, topic checker, ...`` — "log
    merger" should be "log summarizer".
  - Line 139: ``just log merge    # merge logs into latest.log`` — the recipe is
    `just log summary`.

The accurate descriptions to mirror already exist in `AGENTS.md`: the CLI table
(`AGENTS.md:33-43`), the logging section (`AGENTS.md:107-115`), and invariants
(`AGENTS.md:22-29`). **`AGENTS.md` is the source of truth; reword `README.md` to
agree with it, do not invent new descriptions.**

House style (from `AGENTS.md:153-157`): terse, table-heavy, **no em dashes, no
Unicode arrows** — use `to`, `becomes`, or plain hyphens.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Confirm symlink | `readlink CLAUDE.md` | prints `AGENTS.md` |
| Grep for stale tokens | `rg -n "mission_runtime\|px4_ros_sim\|frame_transforms\|log merge\|check-topics\|just hardware" README.md AGENTS.md docs/MCP.md` | no matches |
| Grep for phantom dir | `rg -n "bridges/" README.md AGENTS.md` | no matches (BACKLOG.md may keep it — out of scope) |
| Full quality gate | `just check` | exits 0, `all checks passed.` |

## Scope

**In scope** (the only files you should modify):
- `CLAUDE.md` (replace file with a symlink)
- `AGENTS.md` (fix lines 9, 28, 149)
- `README.md` (fix lines 21, 22, 102, 104, 106, 119, 139)
- `docs/MCP.md` (fix the one `just hardware` reference on line 9)
- `plans/README.md` (status row only)

**Out of scope** (do NOT touch, even though they look related):
- `docs/BACKLOG.md` — its `bridges/` reference (B51) is a deliberate future-idea
  entry, not a claim that the directory exists. Leave it.
- Any source code under `src/`, `tools/`, `tests/`. This is a docs-only plan.
- The CLI behavior itself. You are correcting descriptions, not commands.

## Git workflow

- Branch: `advisor/001-single-source-agent-docs`
- Commit style: conventional commits (repo uses them, e.g.
  `git log` shows `docs(cli): ...`, `refactor(px4): ...`). Suggested message:
  `docs: single-source CLAUDE.md and fix drift in AGENTS/README`.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Make `CLAUDE.md` a symlink to `AGENTS.md`

`CLAUDE.md` is currently a standalone untracked file. Replace it with a symlink
so the two can never diverge again, then track the symlink.

```bash
rm -f CLAUDE.md   # may not exist in a fresh worktree; -f makes this a no-op then
ln -s AGENTS.md CLAUDE.md
git add CLAUDE.md
```

**Verify**: `readlink CLAUDE.md` → prints `AGENTS.md`. Also
`cat CLAUDE.md | head -1` → prints `# AGENTS.md` (the symlink resolves).

### Step 2: Fix the three stale facts in `AGENTS.md`

Make exactly these replacements (match surrounding text exactly):

- Line 9: `just hardware` becomes `just hw`.
- Line 28, invariant #5 — replace:
  `5. Pure logic in `lib/`, nodes in `nodes/`, PX4 specific glue in `bridges/`.`
  with:
  `5. Pure logic in `lib/`, nodes in `nodes/`. ENU/NED conversion stays at the PX4 boundary in `nodes/offboard_controller.py` and `nodes/mission_manager.py`.`
- Line 149 — replace:
  `- New mission phases go in `lib/mission_runtime.py` (add a `PHASE_*` constant and a branch in `tick`). Do not embed phase logic in `nodes/mission_manager.py`.`
  with:
  `- Missions are data-driven YAML state graphs. New behaviors/guards go in `lib/mission/` and are registered in `lib/mission/registry.py`; missions are loaded by `lib/mission/loader.py`. Do not embed phase logic in `nodes/mission_manager.py`.`

**Verify**: `rg -n "just hardware|bridges/|mission_runtime" AGENTS.md` → no matches.

### Step 3: Fix the stale facts in `README.md`

Make exactly these replacements:

- Line 21: `with `just check-topics`` becomes `with `just log topics``.
- Line 22 — replace the whole bullet:
  `- Each node writes logs to `logs/<node>.jsonl`. After a run, `just log merge` produces the compressed logs at `logs/latest.log`, `logs/latest.jsonl`, and a summary at `logs/latest_summary.json`.`
  with:
  `- All processes stream to one logfmt session log, `logs/latest.log` (every line `t=<rel_s> src=<source> ...`). `just log summary` regenerates `logs/latest_summary.json` (run arc, errors, per-scenario pass/fail).`
- Line 102: `# Core nodes, lib, bridges (sim/hardware agnostic)` becomes
  `# Core nodes + lib (sim/hardware agnostic)`.
- Line 104: `# frame_transforms, mission_runtime, StructuredLogger` becomes
  `# frames, mission/ engine, StructuredLogger`.
- Line 106: delete the entire `│   ├── px4_ros_sim/ ...` line (the package does
  not exist). Leave the `px4_msgs/` line below it intact.
- Line 119: `# capabilities CLI, log merger, topic checker, ...` becomes
  `# capabilities CLI, log summarizer, topic checker, ...`.
- Line 139: `just log merge                    # merge logs into latest.log`
  becomes `just log summary                  # regenerate latest_summary.json`.

**Verify**: `rg -n "px4_ros_sim|mission_runtime|frame_transforms|log merge|check-topics|bridges" README.md` → no matches.

### Step 4: Fix the `just hardware` reference in `docs/MCP.md`

Line 9 contains `So both `just sim` and `just hardware` bring it up.` Change
`just hardware` to `just hw`.

**Verify**: `rg -n "just hardware" docs/MCP.md` → no matches.

### Step 5: Run the quality gate

Docs changes do not affect the build, but run the gate to confirm nothing else
regressed and the symlink did not confuse tooling.

**Verify**: `just check` → exits 0, ends with `all checks passed.`

## Test plan

No code changes, so no new unit tests. Verification is the grep gates in each
step plus `just check`. The decisive check is the combined grep:

```bash
rg -n "mission_runtime|px4_ros_sim|frame_transforms|log merge|check-topics|just hardware" README.md AGENTS.md docs/MCP.md
```
→ must return **no matches**.

## Done criteria

ALL must hold:

- [ ] `readlink CLAUDE.md` prints `AGENTS.md`
- [ ] `rg -n "mission_runtime|px4_ros_sim|frame_transforms|log merge|check-topics|just hardware" README.md AGENTS.md docs/MCP.md` returns no matches
- [ ] `rg -n "bridges/" README.md AGENTS.md` returns no matches
- [ ] `just check` exits 0
- [ ] Only files in the in-scope list changed (`git status`)
- [ ] `plans/README.md` status row for 001 updated

## STOP conditions

Stop and report back (do not improvise) if:

- The line numbers/excerpts in "Current state" no longer match the live files
  (the docs were edited after this plan was written).
- `CLAUDE.md` turns out to be tracked or git-ignored in a way that makes the
  symlink swap non-trivial (e.g. `git status` shows it staged, or `.gitignore`
  lists it) — report what you find before forcing it.
- `just check` fails for a reason that looks unrelated to docs (e.g. a build or
  test error). Do not try to fix source code in this plan.

## Maintenance notes

- The whole point is that `CLAUDE.md` now follows `AGENTS.md` automatically.
  Future edits go to `AGENTS.md` only. A reviewer should confirm no future PR
  re-introduces a standalone `CLAUDE.md`.
- `README.md` still duplicates some of `AGENTS.md`'s "core design principles".
  This plan only corrects wrong facts; a future plan could replace the
  overlapping prose with a pointer to `AGENTS.md` to prevent re-drift. Deferred
  intentionally to keep this change low-risk.
- If `bridges/` is ever actually created (BACKLOG B51, the autopilot-abstraction
  `Protocol`), restore the invariant-#5 wording to mention it.
