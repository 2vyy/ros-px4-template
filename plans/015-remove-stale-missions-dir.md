# Plan 015: The `missions/` directory no longer contradicts the real mission system

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 0f93f0e..HEAD -- missions/ README.md`
> If `missions/README.md` or `README.md` changed since this plan was written,
> compare the "Current state" excerpts against the live code before proceeding;
> on a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: docs / tech-debt
- **Planned at**: commit `0f93f0e`, 2026-06-22

## Why this matters

This template's whole point is ergonomic mission *defining*. The `missions/`
directory is a single orphaned README that tells a new author the **exact
opposite of the truth**: it says "a mission here is a launch composition + param
overlay, **not a YAML file**." The real mission system is data-driven YAML state
graphs in `config/missions/*.yaml`, interpreted by `lib/mission/engine.py`, as
correctly documented in `docs/MISSIONS.md` ("a mission is **data, not code**").
The README also describes a `missions/inspect/launch/inspect.launch.py` layout
that does not exist on disk. Worse, the repo's own `README.md` project-structure
table lists this fake `missions/` directory while **omitting** the real
`config/missions/`. A first-time user following these docs is sent down a dead
end. Deleting the contradiction and fixing the structure table removes the
single most misleading artifact in the mission-authoring path.

## Current state

- `missions/` contains exactly one file, `missions/README.md` (959 bytes). There
  is **no** `missions/inspect/` subdirectory and no launch files — confirm with
  `find missions/ -type f` (expected: only `missions/README.md`).
- `missions/README.md` (lines 1-3) currently reads:
  ```
  # Missions (launch recipes)

  A **mission** here is a launch composition + param overlay, not a YAML file. Paths live in `config/paths/`. Profiles live in `config/params/overlays/`.
  ```
  and goes on to describe a `missions/inspect/launch/inspect.launch.py` that does
  not exist.
- The real missions live in `config/missions/`:
  ```
  config/missions/demo.yaml
  config/missions/hover.yaml
  config/missions/marker_hover.yaml
  config/missions/search_relocalize.yaml
  ```
  These are loaded by `mission_manager` via the `mission_file` ROS parameter
  (`src/core/ros_px4_template_core/nodes/mission_manager.py:43,63-67`).
- `docs/MISSIONS.md` (lines 1-12) is the correct, authoritative description and
  already points at `config/missions/*.yaml`.
- `README.md` project-structure table (lines 109-112) currently reads:
  ```
  ├── config/
  │   ├── params/                      # sim/hardware overlays; path_file, enable_marker_hover
  │   └── paths/                       # ENU waypoint lists only
  ├── missions/                        # per-mission launch recipes (e.g. inspect)
  ```
  — it lists the fake `missions/` and never mentions `config/missions/`.
- The **only** two references to the `missions/` directory in tracked text are
  `README.md:112` and `missions/README.md` itself. `AGENTS.md`, `justfile`,
  `tasks.py`, and `docs/MISSIONS.md` do **not** reference it (the loader uses
  `config/missions/`). Confirm in Step 1.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| List missions/ contents | `find missions/ -type f` | only `missions/README.md` |
| Find dir references | `grep -rn "missions/" README.md AGENTS.md docs/ justfile tasks.py \| grep -v "config/missions"` | only `README.md:112` |
| Confirm real missions | `ls config/missions/` | `demo.yaml hover.yaml marker_hover.yaml search_relocalize.yaml` |
| Git status | `git status --porcelain` | only the files you changed |

(`grep`/`find`/`ls` are read-only; no ROS or build needed for this plan.)

## Scope

**In scope**:
- `missions/README.md` (delete) and the `missions/` directory (remove if empty
  after deletion)
- `README.md` (edit the project-structure table only)

**Out of scope** (do NOT touch):
- `config/missions/*.yaml` — the real missions; leave untouched.
- `docs/MISSIONS.md` — already correct.
- `config/params/overlays/*.yaml`, `config/paths/*.yaml` — unrelated.
- The `README.md` "Everyday commands" and "Quick start" sections — a separate
  plan (017) owns those; do not edit them here to avoid a merge conflict.

## Git workflow

- Branch: `advisor/015-remove-stale-missions-dir`
- Commit style: conventional commits, matching `git log` (e.g.
  `docs: remove the stale missions/ dir that contradicts config/missions/`).
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Confirm the directory is dead and unreferenced

Run:
```
find missions/ -type f
grep -rn "missions/" README.md AGENTS.md docs/ justfile tasks.py | grep -v "config/missions"
```

Expected: `find` prints only `missions/README.md`; `grep` prints only one line,
`README.md:112`. If `find` shows any other file under `missions/`, or `grep`
shows a reference from code (`tasks.py`, `justfile`) or a launch file, **STOP**
— the directory may be load-bearing in a way this plan did not anticipate.

### Step 2: Delete the stale directory

```
git rm missions/README.md
```

`missions/` should now be empty and untracked. Confirm:
```
find missions/ -type f
```
Expected: no output (and git no longer tracks anything under `missions/`).

**Verify**: `git status --porcelain` → shows `D  missions/README.md`.

### Step 3: Fix the README project-structure table

In `README.md`, replace the `missions/` line and add the real `config/missions/`
under the `config/` subtree. Change lines 109-113 from:

```
├── config/
│   ├── params/                      # sim/hardware overlays; path_file, enable_marker_hover
│   └── paths/                       # ENU waypoint lists only
├── missions/                        # per-mission launch recipes (e.g. inspect)
├── vehicles/                        # vehicle configurations (e.g. x500.yaml)
```

to:

```
├── config/
│   ├── params/                      # sim/hardware overlays; path_file, enable_marker_hover
│   ├── paths/                       # ENU waypoint lists only
│   └── missions/                    # data-driven mission YAML state graphs (see docs/MISSIONS.md)
├── vehicles/                        # vehicle configurations (e.g. x500.yaml)
```

(The `vehicles/` line is shown only as an anchor so you place the edit correctly;
its text does not change.)

**Verify**: `grep -n "missions" README.md` → shows the new `config/missions/`
line and **no** standalone `├── missions/` line.

## Test plan

No code changes, so no new automated tests. Verification is the grep/find checks
above plus a docs read-through:

- `grep -rn "missions/" README.md AGENTS.md docs/ | grep -v "config/missions"`
  returns nothing (the only remaining `missions` references are `config/missions`).

## Done criteria

ALL must hold:

- [ ] `find missions/ -type f` returns no output (directory removed)
- [ ] `git status --porcelain` shows `missions/README.md` deleted
- [ ] `grep -n "missions" README.md` shows `config/missions/` and no standalone `missions/` row
- [ ] `grep -rn "missions/" README.md AGENTS.md docs/ justfile tasks.py | grep -v "config/missions"` returns nothing
- [ ] No files outside the in-scope list are modified
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- `find missions/` shows files other than `README.md` (the directory has real
  content this plan did not account for).
- `grep` finds a reference to the `missions/` directory from `tasks.py`,
  `justfile`, a launch file, or `AGENTS.md` (something depends on it).
- `README.md` lines 109-113 do not match the "Current state" excerpt (the file
  drifted).

## Maintenance notes

- If a future feature genuinely needs per-mission *launch recipes* (distinct
  from the YAML mission graphs), reintroduce a `missions/` tree with real launch
  files and document the distinction explicitly in `docs/MISSIONS.md` — do not
  resurrect the contradictory README.
- Reviewer should confirm `config/missions/` is the single source of truth for
  mission definitions and that `docs/MISSIONS.md` remains the authoritative doc.
