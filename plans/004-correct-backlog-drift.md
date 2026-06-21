# Plan 004: BACKLOG.md reflects current code (retire done/dead items)

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat 21cbe3d..HEAD -- docs/BACKLOG.md`
> If `docs/BACKLOG.md` changed since this plan was written, compare the
> "Current state" excerpts against the live file before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: docs
- **Planned at**: commit `21cbe3d`, 2026-06-21

## Why this matters

`docs/BACKLOG.md` opens with "All items below are **verified against current
code** (done items removed)" but three entries have drifted: one is already
implemented, and two reference code that was deleted or superseded. A backlog
that lists finished work as open is worse than no backlog: it sends an agent to
"fix" something that is already correct, or to restore a file that was
deliberately removed. This plan re-aligns the backlog with reality so its own
promise holds. It is docs-only and touches no code.

## Current state

`docs/BACKLOG.md` at commit `21cbe3d`. The drifted facts, verified against the
live tree:

- **B27 is done.** Line 20 reads:
  `| B27 | Extract \`lib/offboard_fsm.py\` from \`offboard_controller\` node so the state machine is unit-testable | idea | LOW. Today FSM has no test coverage |`
  But `src/core/ros_px4_template_core/lib/offboard_fsm.py` exists (a pure
  `tick(FsmInputs)` state machine), `nodes/offboard_controller.py:28` imports
  `NAV_STATE_OFFBOARD` from it and calls it in `_update_state_machine`
  (`offboard_controller.py:231-254`), and `tests/unit/test_offboard_fsm.py`
  has 7 unit tests. The "no test coverage" claim is false.

- **B53 references a deleted file (twice).** Line 32 (the B53 row Notes) ends
  with `\`tools/fault_inject.py\` for GPS dropout / wind / motor failure`, and
  line 46 (Top-3 strategic, item 3) ends with `seedable physics, \`tools/fault_inject.py\`.`
  `tools/fault_inject.py` was deleted (it is gone from the tree; `git ls-files
  tools/fault_inject.py` returns nothing). The determinism *idea* stands; only
  the dead file reference must go.

- **B55's premise is already implemented.** Line 34 reads:
  `| B55 | Mission DAG / composable behaviors — replace \`mission_runtime.tick\` if/elif over 4 hardcoded phases; pluggable phase modules; YAML schema for non-survey missions (orbit, RTL, search-pattern, formation) | idea | Won't scale past ~3 mission types |`
  There is no `mission_runtime.tick` if/elif. Missions are data-driven: the
  `src/core/ros_px4_template_core/lib/mission/` package (engine, loader,
  registry, behaviors, guards) loads YAML state graphs. What actually remains
  is *more mission types* (behaviors/guards + YAML for orbit/RTL/search), not
  the engine rewrite.

- **B51 is fine — verify, do not edit.** Line 30 describes an autopilot
  abstraction `Protocol` "in `bridges/`". `bridges/` does not exist yet; the
  entry is phrased as a future idea ("Autopilot abstraction ... Pay before
  mission #5"), not a claim that the directory exists. This is consistent with
  how plan 001 left invariant wording. Leave B51 unchanged unless its text
  asserts the directory already exists (it does not).

The "Verified done (removed from tracking)" table is at the bottom
(`docs/BACKLOG.md:50-60`), with rows like
`| B13 | \`frame_transforms.py\` now has velocity, yaw, and quaternion conversions ... |`.
B27 moves into this table.

House style (from `AGENTS.md`): terse, table-heavy, **no em dashes, no Unicode
arrows** — use `to`, `becomes`, or plain hyphens.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Confirm B27 is implemented | `ls src/core/ros_px4_template_core/lib/offboard_fsm.py tests/unit/test_offboard_fsm.py` | both paths print (exist) |
| Confirm fault_inject is gone | `git ls-files tools/fault_inject.py` | empty output |
| Confirm no dead refs remain | `rg -n "fault_inject\|mission_runtime" docs/BACKLOG.md` | no matches |
| Confirm B27 left the open table | `rg -n "B27" docs/BACKLOG.md` | one match, inside the "Verified done" table |

## Scope

**In scope** (the only files you should modify):
- `docs/BACKLOG.md`
- `plans/README.md` (status row only — skip if a reviewer told you they own the index)

**Out of scope** (do NOT touch):
- Any source under `src/`, `tools/`, `tests/`. This plan changes documentation
  only; it does not add, restore, or delete code.
- The strategic entries B51, B52, B54, B56, B57 (other than the B53 file-ref
  fix). Their ideas are still open; do not reword or remove them.
- `tools/check_topics.py` / `docs/TOPICS.md` (that is plan 006).

## Git workflow

- Branch: `advisor/004-correct-backlog-drift`
- Commit style: conventional commits. Suggested message:
  `docs(backlog): retire done B27 and fix dead refs in B53/B55`.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Retire B27 (move from open table to "Verified done")

Delete the B27 row from the "Tooling / Developer Experience" table (line 20).
Add a row to the "Verified done (removed from tracking)" table at the bottom,
matching the existing rows' two-column shape:

`| B27 | \`lib/offboard_fsm.py\` is a pure \`tick(FsmInputs)\` state machine, imported by \`offboard_controller\`; \`tests/unit/test_offboard_fsm.py\` covers it |`

**Verify**: `rg -n "B27" docs/BACKLOG.md` returns exactly one match, and it is
in the bottom "Verified done" table (line number > the "Verified done" heading).

### Step 2: Strip the deleted `fault_inject.py` from B53 and the Top-3 list

In the B53 row (line 32), replace the trailing
`\`tools/fault_inject.py\` for GPS dropout / wind / motor failure`
with
`fault scenarios (GPS dropout / wind / motor failure) wired into the e2e harness`.

In the Top-3 strategic paragraph for B53 (line 46), replace
`seedable physics, \`tools/fault_inject.py\`.`
with
`seedable physics, and fault scenarios in the e2e harness.`

(The "right shape" note in plan 002 was that fault testing belongs as a
`tests/scenarios/NN_fault_*.py` plus a `capabilities.toml` entry, not a manual
tool — this wording matches that.)

**Verify**: `rg -n "fault_inject" docs/BACKLOG.md` returns no matches.

### Step 3: Reword B55 to what actually remains

Replace the B55 row (line 34) with:

`| B55 | More mission types on the data-driven \`lib/mission/\` engine: behaviors/guards + YAML state graphs for non-survey missions (orbit, RTL, search-pattern, formation) | idea | Engine already data-driven; gap is the behavior/guard + mission-YAML library |`

**Verify**: `rg -n "mission_runtime" docs/BACKLOG.md` returns no matches; the B55
row no longer claims an if/elif rewrite.

### Step 4: Verify B51 needs no change

Read the B51 row (line 30). Confirm it phrases `bridges/` as a future idea, not
an existing directory. If it only *proposes* the abstraction (it does), make no
edit. If — and only if — it asserts `bridges/` already exists, that would be a
new drift; in that case STOP and report rather than guessing the rewrite.

**Verify**: `rg -n "bridges/" docs/BACKLOG.md` still returns the B51 line
(unchanged), and no other doc claims the directory exists.

### Step 5: Sanity-check the whole file

**Verify**:
- `rg -n "fault_inject|mission_runtime" docs/BACKLOG.md` → no matches.
- `rg -n "B27" docs/BACKLOG.md` → one match, in the "Verified done" table.
- The file still has its three section headings (Correctness / Bugs, Tooling /
  Developer Experience, Strategic) and the Top-3 + Verified-done sections.

## Test plan

No code, no new tests. Verification is the grep gates in each step. The decisive
check is Step 5's combined grep returning no matches plus B27 appearing only in
the done table.

## Done criteria

ALL must hold:

- [ ] `rg -n "fault_inject|mission_runtime" docs/BACKLOG.md` returns no matches
- [ ] `rg -n "B27" docs/BACKLOG.md` returns exactly one match, in the "Verified done" table
- [ ] B55 row no longer mentions an if/elif phase rewrite; mentions `lib/mission/`
- [ ] B51 row unchanged
- [ ] No files outside the in-scope list are modified (`git status`)
- [ ] `plans/README.md` status row for 004 updated (unless a reviewer owns the index)

## STOP conditions

Stop and report back (do not improvise) if:

- The line numbers/excerpts in "Current state" no longer match the live file.
- `src/core/ros_px4_template_core/lib/offboard_fsm.py` or
  `tests/unit/test_offboard_fsm.py` does NOT exist (B27 would not actually be
  done — do not retire it).
- The B51 row asserts `bridges/` already exists (a new drift this plan did not
  anticipate).

## Maintenance notes

- When a strategic item ships, move it to the "Verified done" table rather than
  deleting it outright, matching the existing pattern.
- If determinism work (B53) lands as a fault scenario, record the
  `capabilities.toml` id so the backlog points at the exercised capability.
