# Plan 019: A committed `.env.example` documents the required environment

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result. If anything in "STOP
> conditions" occurs, stop and report. When done, update this plan's row in
> `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 0f93f0e..HEAD -- README.md .gitignore`
> If either changed, compare the "Current state" excerpts before proceeding.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: dx
- **Planned at**: commit `0f93f0e`, 2026-06-22

## Why this matters

The repo requires a `.env` with three keys (`PX4_DIR`, `ROS_SETUP`,
`PX4_VERSION`), loaded by `tasks.py:_load_dotenv` and `justfile` (`set
dotenv-load := true`). Onboarding tells the user to hand-`echo` them into `.env`
(`README.md:67-69`), which is error-prone (quoting, paths) and undiscoverable
once you have cloned. The standard affordance — a committed `.env.example` the
user copies and edits — is missing. Adding it is a few minutes and removes a
real first-run friction point, with zero risk: `.env` itself stays gitignored.

## Current state

- `README.md:65-69` (Quick start step 1):
  ```
  1. Add PX4, ROS, and version paths to `.env` (adjust paths if yours differ):

  ```bash
  echo -e 'PX4_DIR=/path/to/PX4-Autopilot\nROS_SETUP=/opt/ros/jazzy/setup.bash\nPX4_VERSION=v1.17.0\n' >> .env
  ```
  ```
- `tasks.py:37-49` (`_load_dotenv`) parses `.env` as `KEY=VALUE` lines, skipping
  blanks and `#` comments, stripping quotes; it only sets keys not already in the
  environment.
- `.gitignore:8` ignores `.env` (so `.env.example` is NOT ignored and will be
  tracked — confirm in Step 1).
- There is no `.env.example` in the tree.
- The three keys and their meaning (from `README.md` and `AGENTS.md`):
  - `PX4_DIR` — absolute path to your PX4-Autopilot clone (lives outside this
    repo; `${PX4_DIR}/build/px4_sitl_default/bin/px4` must exist after building
    PX4).
  - `ROS_SETUP` — path to the ROS 2 Jazzy setup script, default
    `/opt/ros/jazzy/setup.bash`.
  - `PX4_VERSION` — PX4 firmware tag, e.g. `v1.17.0` (must match the `px4_msgs`
    branch `release/1.17`).

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Confirm .env.example not ignored | `git check-ignore .env.example; echo "ignored=$?"` | `ignored=1` (i.e. NOT ignored) |
| Confirm tracked after add | `git status --porcelain .env.example` | shows `A  .env.example` (or `??` before add) |
| Re-grep README | `grep -n ".env.example" README.md` | shows the new instruction |

## Scope

**In scope**:
- `.env.example` (create)
- `README.md` — quick-start step 1 only (replace the `echo` with a copy
  instruction)

**Out of scope** (do NOT touch):
- `.gitignore` — `.env` must remain ignored; do NOT add `.env.example` to it.
- `tasks.py` / `justfile` dotenv loading — unchanged.
- Any real `.env` file — never create, read aloud, or commit it. If a `.env`
  exists locally, do not copy its values into `.env.example`; use placeholders
  only.

## Git workflow

- Branch: `advisor/019-add-env-example`
- Conventional commit (e.g. `docs: add .env.example for first-run onboarding`).
- Do NOT push or open a PR unless instructed.

## Steps

### Step 1: Confirm `.env.example` will be tracked (not gitignored)

```
git check-ignore .env.example; echo "exit=$?"
```
Expected `exit=1` (git does not ignore it). If `exit=0`, **STOP** — `.gitignore`
has a pattern that would swallow the example file; report it.

### Step 2: Create `.env.example`

Write `.env.example` with the three keys, placeholder values, and a one-line
comment each. Use placeholders, never real local paths/values:
```
# Copy to .env and edit for your machine:  cp .env.example .env
# .env is gitignored; this example is the documented template.

# Absolute path to your PX4-Autopilot clone (built for SITL).
# ${PX4_DIR}/build/px4_sitl_default/bin/px4 must exist after building PX4.
PX4_DIR=/path/to/PX4-Autopilot

# Path to the ROS 2 Jazzy setup script.
ROS_SETUP=/opt/ros/jazzy/setup.bash

# PX4 firmware tag; must match the px4_msgs branch release/1.17.
PX4_VERSION=v1.17.0
```

**Verify**: `git status --porcelain .env.example` shows it as a new untracked/
added file; `grep -c "=" .env.example` ≥ 3.

### Step 3: Point the README at it

Replace the `README.md` quick-start step 1 fenced `echo` block (lines 67-69)
with a copy-then-edit instruction:
```
1. Copy the environment template and edit paths for your machine:

```bash
cp .env.example .env       # then edit .env: PX4_DIR, ROS_SETUP, PX4_VERSION
```
```

**Verify**: `grep -n ".env.example" README.md` shows the new line; `grep -n "echo -e 'PX4_DIR" README.md` returns nothing.

## Test plan

No code; verification is the git-ignore check, the file-content check, and a
read-through confirming the three keys match what `_load_dotenv` and the launch
expect. Optionally confirm `_load_dotenv` parses the example by pointing it at a
copy in a temp dir, but this is not required.

## Done criteria

ALL must hold:

- [ ] `.env.example` exists, is tracked by git, and contains `PX4_DIR`, `ROS_SETUP`, `PX4_VERSION` with placeholder values (no real secrets/paths)
- [ ] `git check-ignore .env.example` returns nonzero (file is NOT ignored)
- [ ] `grep -n ".env.example" README.md` shows the new copy instruction; the old `echo -e 'PX4_DIR...` line is gone
- [ ] `.gitignore` still ignores `.env` and was not modified
- [ ] Only the in-scope files are modified
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report if:

- `.env.example` turns out to be gitignored (Step 1 `exit=0`).
- A real `.env` exists and you are tempted to derive example values from it — do
  not; use placeholders.
- The README quick-start block does not match "Current state".

## Maintenance notes

- If a new required env var is introduced (e.g. for hardware bring-up), add it to
  `.env.example` with a comment in the same commit that starts consuming it.
- Reviewer: confirm no real machine paths or credentials leaked into the example.
