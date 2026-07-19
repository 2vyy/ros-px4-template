# Plan 085: Remove the record/analyze (bag + ULog + skein) pipeline

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat d44126d..HEAD -- tasks.py justfile tools/bag_recorder.py tools/ulog_retrieve.py tools/skein_analyze.py docs/SIM.md README.md AGENTS.md docs/BACKLOG.md`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MED (product decision — the code evidence is HIGH-confidence)
- **Depends on**: none (do not interleave with 084 in `tasks.py`; land one, rebase the other)
- **Category**: tech-debt (feature removal)
- **Planned at**: commit `d44126d`, 2026-07-18

## Why this matters

The opt-in recording pipeline (`just sim start --record` → MCAP bag +
PX4 ULog → `just analyze` via the sibling `skein` repo) has **zero automated
consumers**: no scenario, no e2e path, no claims-ladder path, and no test
outside the three unit files that test the pipeline itself ever passes
`--record` or invokes `analyze`. It depends on an un-vendored sibling
checkout (`../skein`) that a fresh clone does not have. Its dedicated runbook
(`docs/SKEIN.md`) was already deleted in the 2026-07-18 docs shrink
(`d6bd2ae`). What remains is ~360 LOC of tools, ~475 LOC of tests, ~80 LOC of
`tasks.py` wiring (~33 branch statements), a justfile recipe, and doc
sections describing a workflow nothing exercises. Claims evidence
(`just cap record`, `tests/evidence/`) is fully independent —
`tools/cap_evidence.py` imports only stdlib and is untouched by this removal.

**Removal justification (the "absolutely justified" bar):**
- Consumers: `grep -rn "record\|analyze" tests/scenarios/ tests/unit/test_tasks_e2e_groups.py`
  → nothing but the pipeline's own three unit files.
- Docs: only `docs/SIM.md` §"Record and analyze a run (skein)", one README
  sentence each at lines 135 and 185, the `--record` flag listing in
  AGENTS.md:45, and BACKLOG B53.
- History: no substantive commit since the original feature series
  (plans 009–013, 048, June 2026); the maintainer opted recording default-off
  in plan 048 and deleted its runbook in the last commit.
- Independence: `tools/cap_evidence.py` imports json/subprocess/sys/tomllib/
  pathlib only (verified at `d44126d`).

**What this forecloses (the honest cost):** `docs/BACKLOG.md` B53 frames the
recording half as groundwork for a future `just replay <run>`, and the
claims-ladder spec reserves a future `sim-golden` rung that skein grading
would feed. Removing now means re-adding later if that direction is ever
picked up — git history preserves the implementation.

## Current state

- `tools/bag_recorder.py` (139 LOC) — starts/stops `ros2 bag record`, owns
  `logs/runs/<id>/` run DIRS, `BAG_PIDFILE`, `RUNS_DIR`, `new_run_dir()`.
- `tools/ulog_retrieve.py` (73 LOC) — copies the freshest PX4 SITL ULog into
  `logs/runs/<id>/session.ulg` at teardown.
- `tools/skein_analyze.py` (93 LOC) — pure helpers for the `analyze` command
  (`resolve_skein_dir`, `resolve_run_dir`, `find_bag_mcap`, `overlay_argv`,
  `query_argv`, `skein_venv_dir`, `AnalyzeError`).
- `tasks.py` wiring:
  - imports at lines 185 (`import bag_recorder`), 194 (`import skein_analyze`),
    196 (`import ulog_retrieve`);
  - `_teardown()` hook:
    ```python
    # tasks.py:361-370 (excerpt)
    was_recording = bag_recorder.BAG_PIDFILE.exists()
    bag_recorder.stop()  # graceful SIGINT first; finalizes the MCAP. Non-fatal.
    ...
    if was_recording:
        # PX4 is dead now, so its ULog is final. Best-effort, SITL-only.
        ulog_retrieve.retrieve(bag_recorder.RUNS_DIR / "latest")
    ```
  - `sim start`'s `--record` option (`tasks.py:899-900`) and its branch:
    ```python
    # tasks.py:944-954
    if record:
        run_dir = bag_recorder.new_run_dir()
        bag_proc = bag_recorder.start(run_dir, env)
        rec_detail = (...)
    else:
        bag_recorder.BAG_PIDFILE.unlink(missing_ok=True)
        rec_detail = "recording: off (use --record)"
    ```
    (`rec_detail` feeds the READY verdict line at `:955-960`.)
  - the whole `analyze` command (`tasks.py:989-1054`).
- `justfile:47-49`:
  ```
  # Analyze a recorded run with skein (overlay bag+ULog; optional --query)
  analyze *args:
      @just _run analyze "$@"
  ```
- Tests: `tests/unit/test_bag_recorder.py`, `tests/unit/test_ulog_retrieve.py`,
  `tests/unit/test_skein_analyze.py`.
- Docs: `docs/SIM.md` section "## Record and analyze a run (skein)"
  (the ~4 paragraphs + code block after the marker-assets paragraph);
  `README.md:135` (`just analyze` line in the commands block) and
  `README.md:185` (the sentence starting "`just sim start --record`
  captures a ROS bag …"); `AGENTS.md:45` lists `--record` among the sim
  flags; `docs/BACKLOG.md:41` row B53 says "The recording half shipped: …".
- Interaction to preserve: `tools/run_supervisor.py` writes run-record FILES
  into the same `logs/runs/` where bag recording wrote run DIRS
  (`_record_files` already filters to files — see its docstring "the
  bag-recording run DIRS coexist untouched"). Run records are UNRELATED to
  this pipeline and must keep working.
- `check_docs.py` machine-verifies backticked tokens in README/AGENTS/docs —
  removing the code without the doc mentions (or vice versa) fails `just check`.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Full gate | `just check` (host without ROS: `distrobox enter ubuntu -- bash -lc "just check"`) | exit 0 |
| Unit subset | `uv run pytest tests/unit -q` | all pass, ~24 fewer tests than before |
| Docs check alone | `uv run python tools/check_docs.py` | exit 0 |
| Reference sweep | `grep -rn "bag_recorder\|ulog_retrieve\|skein" tasks.py tools/ tests/ justfile README.md AGENTS.md docs/*.md` | no matches (except plans/ and docs/superpowers/ archives) |

## Scope

**In scope** (the only files you should modify/delete):
- Delete: `tools/bag_recorder.py`, `tools/ulog_retrieve.py`,
  `tools/skein_analyze.py`, `tests/unit/test_bag_recorder.py`,
  `tests/unit/test_ulog_retrieve.py`, `tests/unit/test_skein_analyze.py`
- Edit: `tasks.py`, `justfile`, `docs/SIM.md`, `README.md`, `AGENTS.md`,
  `docs/BACKLOG.md`, `plans/README.md` (status row)

**Out of scope** (do NOT touch, even though they look related):
- `tools/run_supervisor.py` and everything about run RECORDS in `logs/runs/`
  — a different, live feature that merely shares the directory.
- `tools/cap_evidence.py`, `tools/capabilities.py`, `tests/evidence/`,
  `just cap record` — the claims ledger is independent and stays.
- `plans/009-013`, `plans/048`, `docs/superpowers/` — historical archives;
  leave every mention there.
- `tasks.py` `clean` command if it merely wipes `logs/` wholesale (check —
  only remove code that references the deleted modules by name).

## Git workflow

- Branch: `advisor/085-remove-record-analyze`
- Conventional commits; suggested: `refactor(cli)!: remove the opt-in bag/ULog/skein record-analyze pipeline`
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Strip the `tasks.py` wiring

Remove: the three imports (lines 185, 194, 196); the `record` option and its
`if record:/else:` block in `sim start` — replace `rec_detail` usage by
dropping that entry from the READY-verdict list (keep the other three
entries); the `was_recording`/`bag_recorder.stop()`/`ulog_retrieve.retrieve`
lines in `_teardown()` (keep `sim_cleanup.teardown()`, the heartbeat/RUN_PID
unlinks, and the STOPPED verdict exactly as they are); the entire `analyze`
command.

**Verify**: `grep -n "bag_recorder\|ulog_retrieve\|skein" tasks.py` → no
matches; `uv run python tasks.py --help` → exits 0, no `analyze` command.

### Step 2: Delete the three tools and their three test files

**Verify**: `uv run pytest tests/unit -q` → all pass, none error on import.

### Step 3: Remove the justfile recipe

Delete the `analyze` recipe and its comment (`justfile:47-49`).

**Verify**: `just --list` → no `analyze` row.

### Step 4: Update the docs in the same change

- `docs/SIM.md`: delete the "## Record and analyze a run (skein)" section
  entirely.
- `README.md`: delete line 135 (`just analyze …`) and, at line 185, delete
  the sentence beginning "`just sim start --record` captures a ROS bag…"
  (keep the preceding `just log topics` sentence).
- `AGENTS.md:45`: remove `--record` from the flags list (leave the rest of
  the line untouched).
- `docs/BACKLOG.md` B53: reword the note — the recording half no longer
  ships; e.g. "Recording/analyze pipeline was removed in plan 085 (no
  consumers); resurrect from git history (plans 009–013, 048) if replay is
  ever picked up. Fault injection was deliberately CUT (plan 002); do not
  re-add without new grounding." Keep the row (the *idea* stays open).

**Verify**: `uv run python tools/check_docs.py` → exit 0;
`grep -rn "skein\|--record" README.md AGENTS.md docs/SIM.md docs/BACKLOG.md`
→ only the B53 history note.

### Step 5: Full gate + live regression

**Verify**: `just check` → exit 0. Operator sign-off (live sim available):
`just sim start` → READY verdict now lists three checks (no "recording:"
entry); `just stop` → STOPPED verdict, 0 survivors; `just run
01_arm_takeoff` → PASS with a run record in `logs/runs/` (proves run
records survived the removal).

## Test plan

- No new tests: this is a pure deletion; the existing suite minus the three
  deleted files is the net. `test_run_supervisor.py` passing is the guard
  that run records are unaffected.
- Expected test-count drop: the three deleted files' tests (~24 tests).

## Done criteria

- [ ] `just check` exits 0
- [ ] `grep -rn "bag_recorder\|ulog_retrieve\|skein_analyze" tasks.py tools/ tests/ justfile` → no matches
- [ ] `grep -rn "skein" README.md AGENTS.md docs/*.md` → only the BACKLOG B53 history note
- [ ] `uv run python tasks.py sim start --help` → no `--record` flag
- [ ] `just --list` → no `analyze` recipe
- [ ] No files outside the in-scope list modified (`git status`)
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- Any file outside the pipeline imports `bag_recorder`, `ulog_retrieve`, or
  `skein_analyze` (the audit found none at `d44126d`; a new importer means
  the disuse premise broke).
- `check_docs.py` flags a token this plan's doc edits didn't anticipate —
  report the token rather than allowlisting it.
- The maintainer has marked this plan REJECTED in `plans/README.md` (this is
  a product decision; the index row is the veto point).
- Removing `rec_detail` changes the READY verdict in a way
  `tests/unit/` pins differently than expected — report the failing test.

## Maintenance notes

- This is the repo's largest single erasure (~950 LOC net). A reviewer
  should confirm: (1) `_teardown()` still prints the same STOPPED verdict,
  (2) `logs/runs/` run RECORDS still write and prune, (3) no doc references
  survive outside archives.
- If replay/sim-golden grading is ever pursued, resurrect from tags at
  plans 009–013/048 rather than re-designing; the clock-reconciliation
  design lives in the skein repo's docs.
- Deferred deliberately: nothing. The `logs/runs/latest` symlink logic dies
  with `bag_recorder`; run records never used it.
