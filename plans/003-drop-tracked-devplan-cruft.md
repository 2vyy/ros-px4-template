# Plan 003: Stop shipping stale dev-plan files with the template

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git ls-files docs/superpowers`
> Expect exactly the three files listed in "Current state". If the set differs,
> compare against this plan before proceeding; on a mismatch, treat it as a STOP
> condition.

## Status

- **Priority**: P3
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: docs / tech-debt
- **Planned at**: commit `5175284`, 2026-06-20

## Why this matters

This is a *template* — people clone it to start new projects. The
`docs/superpowers/` directory is git-ignored (`.gitignore:13`), so it is
correctly treated as local scratch space for the maintainer's planning history.
But three plan files were force-added before the ignore rule and remain tracked.
They travel to every clone, dropping ~60KB of one author's historical, project-
specific planning narrative into a fresh template where it has no relevance.
Removing them makes the template clean without losing anything: the maintainer's
local copies stay on disk (they are git-ignored), only the *tracked* copies go.

## Current state

`docs/superpowers/` is git-ignored but three files are tracked anyway:

- `git ls-files docs/superpowers` returns exactly:
  - `docs/superpowers/plans/2026-05-28-fast-warm-relaunch.md`
  - `docs/superpowers/plans/2026-05-28-honest-bench-relaunch.md`
  - `docs/superpowers/plans/2026-05-29-sim-speed-cleanup.md`
- `.gitignore:13` contains `docs/superpowers/`, so once these are removed from
  the index they will not be re-added by a normal `git add`.
- These are historical implementation plans for already-merged work (warm
  relaunch, bench, sim-speed cleanup). No tracked file references them.

Confirm nothing tracked links to them:
`rg -l "superpowers/plans" -- ':!docs/superpowers'` (run from repo root) should
return no matches.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| List tracked superpowers files | `git ls-files docs/superpowers` | empty after removal |
| Confirm no inbound links | `rg -l "superpowers/plans" -- ':!docs/superpowers'` | no matches |
| Confirm local copies survive | `ls docs/superpowers/plans/ \| wc -l` | non-zero (files remain on disk, now untracked) |

## Scope

**In scope**:
- Untrack (but keep on disk) the three files above via `git rm --cached`.
- `plans/README.md` (status row only).

**Out of scope** (do NOT touch):
- The local files on disk — do **not** `rm` them, only `git rm --cached`. They
  are the maintainer's working notes.
- `.gitignore` — it already ignores the directory correctly. No change needed.
- Any other doc under `docs/`. `BACKLOG.md`, `FRAMES.md`, `TOPICS.md`,
  `MISSIONS.md`, `MCP.md` are live docs and stay tracked.

## Git workflow

- Branch: `advisor/003-drop-devplan-cruft`
- Commit style: conventional commits. Suggested message:
  `chore: stop tracking local dev-plan files (already git-ignored)`.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Verify the tracked set matches the plan

```bash
git ls-files docs/superpowers
```

**Verify**: prints exactly the three files in "Current state". If the set
differs (more or fewer files, different names), **STOP** and report — the index
changed since this plan was written.

### Step 2: Untrack the three files, keeping them on disk

```bash
git rm --cached docs/superpowers/plans/2026-05-28-fast-warm-relaunch.md \
                docs/superpowers/plans/2026-05-28-honest-bench-relaunch.md \
                docs/superpowers/plans/2026-05-29-sim-speed-cleanup.md
```

(`--cached` removes from the index only; the files stay on disk and are now
covered by the existing `.gitignore` rule.)

**Verify**:
- `git ls-files docs/superpowers` → empty.
- `ls docs/superpowers/plans/ | wc -l` → still non-zero (local copies intact).

## Test plan

No code involved. Verification is the two greps/`git ls-files` checks above.
Optionally run `just check` to confirm the repo is still healthy; it is
unaffected by this change.

## Done criteria

ALL must hold:

- [ ] `git ls-files docs/superpowers` returns empty
- [ ] The three files still exist on disk (`ls docs/superpowers/plans/`)
- [ ] `rg -l "superpowers/plans" -- ':!docs/superpowers'` returns no matches
- [ ] No other tracked files modified except `plans/README.md`
- [ ] `plans/README.md` status row for 003 updated

## STOP conditions

Stop and report back (do not improvise) if:

- `git ls-files docs/superpowers` does not match the three expected files.
- A tracked file outside `docs/superpowers/` links to one of these plans
  (removing them would create a broken link).

## Maintenance notes

- After this, `docs/superpowers/` behaves as intended: fully local, never
  shipped. A reviewer should confirm no future `git add -f` re-tracks files
  there.
- If the project ever wants to ship reference plans with the template, put them
  somewhere not git-ignored (e.g. `docs/examples/`) rather than un-ignoring
  `docs/superpowers/`.
