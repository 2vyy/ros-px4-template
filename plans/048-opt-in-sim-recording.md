# Plan 048: Make bag/ULog recording opt-in (`just sim --record`)

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report - do not improvise. When done, update the status row for this plan
> in `plans/README.md` - unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat ead4cc6..HEAD -- tasks.py tools/bag_recorder.py docs/SKEIN.md`
> Plans 031/033/037/039/045 legitimately edit `tasks.py`; plan 026 edits
> `bag_recorder.py`'s fd handling - reconcile. Any other drift vs the
> excerpts is a STOP condition.

## Status

- **Priority**: P3
- **Effort**: S
- **Risk**: LOW-MED (changes a default; the operator explicitly chose this - see Decision below)
- **Depends on**: none
- **Category**: dx
- **Planned at**: commit `ead4cc6`, 2026-07-06

## Decision (operator-approved)

Every `just sim` currently starts an MCAP bag recorder and every teardown
retrieves the PX4 ULog into `logs/runs/<id>/`. That subsystem is verified and
stays - but it serves occasional flight-forensics (`just analyze`), while its
costs (an extra detached process in every boot, per-run disk growth, the fd
leak plan 026 exists to fix, and the only cross-repo coupling in the template
via sibling-checkout skein) are paid on every run. Per the toolchain vetting,
recording becomes **opt-in**: `just sim --record`. Default `just sim` boots
with zero skein-adjacent moving parts. `just analyze` is unchanged and simply
requires a recorded run to exist.

## Current state

- `tasks.py` `sim` command:
  - Options block (lines 462-472): `gui`, `world`, `model`, `vision`,
    `speed`, `overlay`, `build`, `timeout`. No record flag.
  - Recording start, AFTER readiness is confirmed (lines 543-556):

```python
    # readiness confirmed past this point
    run_dir = bag_recorder.new_run_dir()
    bag_proc = bag_recorder.start(run_dir, env)
    rec_detail = (
        f"recording -> {run_dir.relative_to(ROOT)}/bag"
        if bag_proc is not None
        else "recording: DISABLED (recorder failed to start)"
    )
    print(
        format_ready(
            ["/fmu topics up", "rosbridge:9090", "GCS params committed", rec_detail],
            elapsed,
        )
    )
```

- `tasks.py` `_teardown` (lines 183-196) already degrades cleanly when
  nothing was recorded: `was_recording = bag_recorder.BAG_PIDFILE.exists()`
  gates both `bag_recorder.stop()`'s effect and the
  `ulog_retrieve.retrieve(...)` call. **No teardown changes are needed** -
  verify this claim by reading the excerpt in the live file.
- `bag_recorder.start` is called from EXACTLY ONE site (line 545; confirmed
  by `rg -n "bag_recorder.start" tasks.py`). `hw` and the e2e group runner do
  not record.
- Docs that state the always-on behavior: `docs/SKEIN.md` (the
  `just sim` -> `logs/runs/<id>/` pipeline description) and possibly a README
  line - grep in Step 3.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Lint | `uv run ruff check tasks.py` | exit 0 |
| Flag plumbing (no sim needed) | `uv run tasks.py sim --help` | `--record` listed with help text |
| Live default (operator) | `just sim` then `just stop` | READY verdict WITHOUT `recording ->`; no new `logs/runs/<id>` |
| Live opt-in (operator) | `just sim --record` then `just stop` then `just analyze latest` | recording verdict; run dir + ULog; analyze works |
| Full gate | `just check` | exit 0 |

## Scope

**In scope**:
- `tasks.py` (`sim` command only: one option + one conditional)
- `docs/SKEIN.md` (reflect the flag)
- `README.md` / `AGENTS.md` sim-flags lines IF they enumerate sim flags
  (grep in Step 3; AGENTS.md lists sim flags in two places)

**Out of scope**:
- `tools/bag_recorder.py`, `tools/ulog_retrieve.py`, `tools/skein_analyze.py`
  - unchanged; the subsystem is kept, not trimmed.
- `_teardown` - already conditional on the pidfile.
- Recording in `hw`/e2e - they never recorded; do not add the flag there.
- An env-var alias (`SIM_RECORD=1`) - one spelling only; add later if a
  workflow actually needs it.

## Git workflow

- Branch: `advisor/048-opt-in-recording`
- Commit style: `feat(sim): make bag/ULog recording opt-in via --record`
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: The flag and the conditional

1. Add to `sim`'s options (after `overlay`, matching the existing style):

```python
    record: bool = typer.Option(
        False, "--record", help="Record an MCAP bag + retrieve the PX4 ULog for `just analyze`."
    ),
```

2. Wrap the recording block:

```python
    # readiness confirmed past this point
    if record:
        run_dir = bag_recorder.new_run_dir()
        bag_proc = bag_recorder.start(run_dir, env)
        rec_detail = (
            f"recording -> {run_dir.relative_to(ROOT)}/bag"
            if bag_proc is not None
            else "recording: DISABLED (recorder failed to start)"
        )
    else:
        rec_detail = "recording: off (use --record)"
```

   The `format_ready` call is unchanged (it still receives `rec_detail`) -
   the verdict now states the recording status either way, per the
   no-bare-done verdict contract.

**Verify**: `uv run ruff check tasks.py` -> exit 0;
`uv run tasks.py sim --help` -> shows `--record`.

### Step 2: Confirm teardown needs nothing

Read `_teardown` in the live file and confirm the `was_recording =
bag_recorder.BAG_PIDFILE.exists()` gate matches the excerpt. If it does,
change nothing. (`bag_recorder.stop()` on a non-recording run must already be
a no-op - it was, at `ead4cc6`, because `stop()` keys off the same pidfile;
confirm by reading `tools/bag_recorder.py`'s `stop`.)

**Verify**: reading only; note the confirmation in your report.

### Step 3: Docs

1. `rg -n "recording|logs/runs" docs/SKEIN.md README.md AGENTS.md` - update
   every line that says recording happens on every `just sim`:
   `just sim` becomes `just sim --record` in the SKEIN.md pipeline
   description, with one added sentence: "Recording is opt-in; a default
   `just sim` records nothing and `just analyze` requires a `--record` run."
2. AGENTS.md sim-flags lines (the Tooling table row and the "Sim flags" line
   under Common workflows): add `--record` to the flag enumeration. Keep the
   house style (no em dashes, terse).

**Verify**: `rg -n "\-\-record" docs/SKEIN.md AGENTS.md` -> matches;
no remaining claim that recording is automatic
(`rg -in "every run|each run" docs/SKEIN.md` - reword any hit that implies
always-on recording).

### Step 4: Full gate + live verification (operator-gated)

1. `just check` -> exit 0.
2. Operator: `just sim` -> READY verdict contains `recording: off`;
   `ls logs/runs/` gained NO new entry; `just stop` -> STOPPED, no ULog-copy
   message.
3. Operator: `just sim --record` -> verdict contains `recording ->
   logs/runs/<id>/bag`; fly nothing, `just stop` -> ULog copied;
   `just analyze latest` -> overlay runs (skein sibling checkout required, as
   before).
4. Regression: `just test e2e` -> exit 0 (e2e never recorded; unchanged).

If you cannot run a sim, complete steps 1-3 and STOP reporting live
verification pending.

## Test plan

`tasks.py` is outside the unit gate (until plan 045's follow-up tests exist);
verification is the flag help output, the two operator boot paths (off/on),
and the e2e regression. The conditional is 6 lines around a verified-working
block, with the pidfile-gated teardown untouched.

## Done criteria

- [ ] `uv run tasks.py sim --help` shows `--record` (default off)
- [ ] `rg -n "bag_recorder.start" tasks.py` -> still exactly one call site, now under `if record:`
- [ ] `_teardown` unchanged (`git diff` does not touch it)
- [ ] Docs updated (SKEIN.md pipeline + AGENTS.md flag lists)
- [ ] `just check` exits 0
- [ ] Live: default-off and opt-in boots verified per Step 4 (or reported as pending operator sign-off)
- [ ] `git status` shows only in-scope files modified
- [ ] `plans/README.md` status row updated

## STOP conditions

- `_teardown` or `bag_recorder.stop()` does NOT match the pidfile-gated
  behavior described (drift since `ead4cc6`) - the "no teardown changes"
  claim fails; report instead of patching teardown ad hoc.
- Any OTHER call site of `bag_recorder.new_run_dir`/`start` appears in
  `tasks.py` (e2e grew recording since this plan was written) - scope drift;
  report.
- The operator wants recording default-ON after all - this plan's premise is
  the opt-in decision; flip nothing without that confirmation in writing.

## Maintenance notes

- If a competition workflow wants always-record, the right lever is a wrapper
  recipe or shell alias, not flipping the default back silently.
- Reviewer: the verdict must never print a `recording ->` path that is not
  actually being recorded; the `rec_detail` branches are the contract.
