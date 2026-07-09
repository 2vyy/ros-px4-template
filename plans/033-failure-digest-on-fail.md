# Plan 033: A failed scenario or e2e run prints a diagnostic digest automatically

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report - do not improvise. When done, update the status row for this plan
> in `plans/README.md` - unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat ead4cc6..HEAD -- tools/log_summary.py tasks.py tests/unit/test_log_summary.py`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none (plan 034 extends this)
- **Category**: dx
- **Planned at**: commit `ead4cc6`, 2026-07-06

## Why this matters

When `just scenario <name>` or `just test e2e` fails, the agent sees the
verdict line and nothing else. The diagnostic material already exists:
`_summarize_logs_silent()` writes `logs/latest_summary.json` (deduped errors,
event timeline) on every run - but silently. The agent must then run
`just log summary` / `just status` / raw `rg` to learn *why*. Printing a
compact digest at the moment of failure removes 2-3 round-trips from the
core autonomous-debug loop this template is built for.

## Current state

- `tools/log_summary.py` - builds the summary dict (`build_run_summary`);
  where the new pure formatting function goes.
- `tasks.py` - orchestrator; `_summarize_logs_silent()` at lines 172-180;
  scenario failure exits around lines 906-925; e2e failure exit around
  lines 860-866.
- `tests/unit/test_log_summary.py` - existing tests to extend.

`_summarize_logs_silent` (`tasks.py:172-180`):

```python
def _summarize_logs_silent() -> None:
    """Regenerate latest_summary.json from latest.log; non-fatal if absent."""
    try:
        summary = build_run_summary(LOG_DIR / "latest.log")
        (LOG_DIR / "latest_summary.json").write_text(
            json.dumps(summary, indent=2) + "\n", encoding="utf-8"
        )
    except Exception as e:
        print(f"Warning: log summary skipped: {e}", file=sys.stderr)
```

Scenario failure paths in `tasks.py` (both must print the digest):

```python
        finally:
            _summarize_logs_silent()
        if not passed:
            raise typer.Exit(int(ExitCode.FAIL))
```

(and the declared-config variant a few lines below:
`if fails > 0: raise typer.Exit(int(ExitCode.FAIL))`.)

E2E failure path (`tasks.py`, in the `e2e` branch):

```python
            if fails > 0 or res_report.returncode != 0:
                raise typer.Exit(int(ExitCode.FAIL))
```

Summary shape produced by `build_run_summary` (see `tools/log_summary.py:55-96`):
keys `run_id`, `duration_s`, `nodes`, `error_count`, `warn_count`,
`event_timeline` (list of `{t, node, event, ...extras}`), `errors`
(list of `{t, node, msg}`, deduped).

Repo conventions: pure logic goes in `tools/` with unit tests; `tasks.py`
stays thin and is NOT covered by `just check` lint/typecheck, so behavior in
`tasks.py` is verified by running commands directly (see round-2 note in
`plans/README.md`). English verdicts, no bare "done" (AGENTS.md).

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Unit tests | `uv run pytest tests/unit/test_log_summary.py -q` | all pass |
| Lint (tasks.py is not in `just check`) | `uv run ruff check tasks.py tools/log_summary.py` | exit 0 |
| Full gate | `just check` | exit 0 |
| Behavior spot-check (no sim needed) | see Step 4 | digest printed |

## Scope

**In scope**:
- `tools/log_summary.py` (add `format_failure_digest`)
- `tasks.py` (print digest on the failing scenario/e2e paths)
- `tests/unit/test_log_summary.py`

**Out of scope**:
- `tools/e2e_report.py`, `tools/status.py` - unchanged.
- Any change to `logs/latest_summary.json`'s schema.
- The PASS paths - the digest prints ONLY on failure (a passing run stays
  quiet; the verdict line is the contract).

## Git workflow

- Branch: `advisor/033-failure-digest`
- Commit style: `feat(logs): print a failure digest when a scenario or e2e run fails`
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Pure formatter in `tools/log_summary.py`

Add a pure function (no I/O, no typer):

```python
def format_failure_digest(summary: dict[str, Any], *, max_errors: int = 8, max_events: int = 10) -> str:
    """Compact human/agent-readable digest of a failed run's summary."""
```

Output shape (plain text, one block; keep it under ~25 lines):

```
--- failure digest (logs/latest_summary.json) ---
run 20260706T120000, 84.2s, 3 errors / 5 warnings
errors:
  t=41.2 offboard_controller: Arm command failed terminally
  ...
last events:
  t=39.0 mission_manager TRANSITION from=takeoff to=search guard=armed_at_altitude
  ...
full log: logs/latest.log | summary: just log summary
```

Rules: take the LAST `max_events` entries of `event_timeline` (most recent
matter); take the first `max_errors` of `errors` (already deduped); render
each timeline extra as `k=v` pairs after the event name; if both lists are
empty, say `no errors or events captured (is logs/latest.log empty?)`.
Match the surrounding code's style (this file has no rich/color output - plain
strings only).

**Verify**: `uv run ruff check tools/log_summary.py` -> exit 0

### Step 2: Unit tests

In `tests/unit/test_log_summary.py`, add (model on the file's existing tests -
they build summaries from synthetic logfmt text):

- `test_digest_lists_errors_and_last_events`: build a summary via
  `build_run_summary` over a synthetic log with 2 errors and 12 events; assert
  the digest contains both error msgs, exactly the last 10 events, and the
  `failure digest` header.
- `test_digest_empty_summary`: summary from a missing/empty log renders the
  "no errors or events captured" line and does not raise.
- `test_digest_caps_errors`: 12 distinct errors -> only 8 rendered.

**Verify**: `uv run pytest tests/unit/test_log_summary.py -q` -> all pass (3 new)

### Step 3: Print the digest on failure in `tasks.py`

Add a helper next to `_summarize_logs_silent`:

```python
def _print_failure_digest() -> None:
    try:
        summary = json.loads((LOG_DIR / "latest_summary.json").read_text(encoding="utf-8"))
        print(format_failure_digest(summary), file=sys.stderr)
    except Exception as e:
        print(f"(failure digest unavailable: {e})", file=sys.stderr)
```

Import `format_failure_digest` alongside the existing
`from log_summary import build_run_summary`-style import at the top of
`tasks.py` (check how `build_run_summary` is imported there and match it).

Call `_print_failure_digest()` immediately before EACH of these existing
failure exits (and no PASS path):

1. scenario, no-declared-config branch: before `raise typer.Exit(int(ExitCode.FAIL))` that follows `if not passed:`
2. scenario, declared-config branch: before the `raise` under `if fails > 0:`
3. e2e: before the `raise` under `if fails > 0 or res_report.returncode != 0:`

**Verify**: `uv run ruff check tasks.py` -> exit 0

### Step 4: Behavior spot-check without a sim

The scenario command fails fast when no sim is up. From the repo root:

```
printf 't=0.100 src=mission_manager level=error msg="synthetic boom"\nt=0.200 src=mission_manager event=TRANSITION from=a to=b\n' > logs/latest.log
uv run python tasks.py scenario 02_hover_hold
```

Expected: the run FAILs (no sim), and stderr includes
`--- failure digest ---` with `synthetic boom` and the TRANSITION event.
Exit code 1. Then clean up: `rm -f logs/latest.log logs/latest_summary.json`.

Note: `just scenario` with a declared config tears down and clears
`logs/latest.log` before running, so the digest will reflect the fresh (empty
or boot-only) log in that path - still correct behavior. If the scenario
instead exits 3 (precondition) before any digest in your environment, that is
acceptable; verify path 1 via the printf approach with a scenario that has no
declared config, or confirm by code-reading that the call sits before the
`raise`.

**Verify**: output as described above.

### Step 5: Full gate

**Verify**: `just check` -> exit 0

## Test plan

Step 2's three unit tests cover the formatter (content, caps, empty).
`tasks.py` wiring is verified by the Step 4 spot-check (the repo's accepted
pattern for `tasks.py`, which is outside the lint/typecheck gate).

## Done criteria

- [ ] `uv run pytest tests/unit/test_log_summary.py -q` passes with 3 new tests
- [ ] `rg -n "_print_failure_digest\(\)" tasks.py` shows 3 call sites, each adjacent to a FAIL `raise typer.Exit`
- [ ] `rg -n "format_failure_digest" tools/log_summary.py tasks.py` -> definition + import + usage
- [ ] `just check` exits 0
- [ ] Step 4 spot-check produced the digest on stderr
- [ ] `git status` shows only in-scope files modified
- [ ] `plans/README.md` status row updated

## STOP conditions

- The failure exits in `tasks.py` are not where the excerpts say (drift).
- `latest_summary.json`'s keys differ from the shape listed above.
- Adding the import to `tasks.py` creates a circular import (tools modules are
  imported flat via `sys.path`; they are not expected to import tasks).

## Maintenance notes

- Plan 034 adds a `px4_events` section to the summary; when it lands,
  `format_failure_digest` should render it too (034 owns that edit).
- Reviewer: confirm the digest goes to stderr and only on failure paths;
  a digest on PASS would pollute the verdict contract.
