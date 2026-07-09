# Plan 034: PX4's own failure reasons (arming denied, failsafe, EKF rejects) reach `log summary` and the failure digest

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report - do not improvise. When done, update the status row for this plan
> in `plans/README.md` - unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat ead4cc6..HEAD -- tools/log_summary.py tests/unit/test_log_summary.py`
> Plan 033 legitimately edits `tools/log_summary.py` first; reconcile with its
> changes (this plan builds on them). Any OTHER drift is a STOP condition.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: LOW
- **Depends on**: plans/033-failure-digest-on-fail.md (digest renders the new section)
- **Category**: dx
- **Planned at**: commit `ead4cc6`, 2026-07-06

## Why this matters

The most common autonomous-debug question is "why won't it arm / why did it
leave OFFBOARD". PX4 answers it in plain text ("Arming denied: ...",
"Failsafe activated ...") and those lines ARE captured into `logs/latest.log`
as `src=px4_sitl ...` lines. But `tools/log_summary.py`'s `parse_logfmt` keeps
only `key=value` tokens, so a free-text PX4 line parses to just `{src, t}` -
its content is dropped. The summary's `errors[]` only collects our nodes'
`level=error` records, and the timeline only collects `event=` records. Net:
PX4's reasons are invisible to `just log summary`, `just status`, the e2e
report, and (after plan 033) the failure digest, and the agent must fall back
to raw `rg src=px4 logs/latest.log`.

## Current state

- `tools/log_summary.py` - parser + summary builder. The lossy parse
  (`parse_logfmt`, lines 24-41) drops tokens without `=`:

```python
    for tok in tokens:
        if "=" not in tok:
            continue
        key, _, val = tok.partition("=")
        rec[key] = val.strip('"')
```

- The summary builder's classification loop (lines 78-96) fills `errors[]`
  from `level == "error"` and `timeline[]` from `"event" in r`. Third-party
  lines have neither.
- `tools/log_capture.py` tags third-party lines as
  `t=<rel> src=<proc> <free text>` (see its module docstring) - the `<proc>`
  names come from the ros2 launch prefix, e.g. `px4_sitl`, `gz_px4_stack`,
  `micro_xrce_agent` (confirm exact names from a real `logs/latest.log` if one
  exists, or from the `name=` fields in `sim/launch/sim_full.launch.py`).
- `tests/unit/test_log_summary.py` - existing tests build summaries from
  synthetic logfmt strings; extend them.
- After plan 033: `format_failure_digest(summary)` exists in the same file.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Unit tests | `uv run pytest tests/unit/test_log_summary.py -q` | all pass |
| Lint | `uv run ruff check tools/log_summary.py tests/unit/test_log_summary.py` | exit 0 |
| Full gate | `just check` | exit 0 |
| Live check (operator) | `just sim && just log summary` | `px4_events` key present |

## Scope

**In scope**:
- `tools/log_summary.py`
- `tests/unit/test_log_summary.py`

**Out of scope**:
- `tools/log_capture.py` - do NOT start injecting `level=`/`event=` fields
  into third-party lines at capture time; the capture filter's contract is
  "lossless except dedup" and other tools grep the raw text.
- `tools/status.py`, `tools/e2e_report.py` - they can adopt `px4_events`
  later; not here.
- `tasks.py`.

## Git workflow

- Branch: `advisor/034-px4-events-summary`
- Commit style: `feat(logs): surface PX4 arming/failsafe reasons in run summary and digest`
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Preserve free text in `parse_logfmt`

Collect non-`k=v` tokens into a `text` field (joined by single spaces), so
third-party lines keep their content:

```python
    extras: list[str] = []
    for tok in tokens:
        if "=" not in tok:
            extras.append(tok)
            continue
        ...
    if extras:
        rec["text"] = " ".join(extras)
```

Keep `_RESERVED` handling unchanged. Note `shlex.split` already strips quotes;
that is fine for matching purposes.

**Verify**: `uv run pytest tests/unit/test_log_summary.py -q` -> existing tests still pass

### Step 2: Pattern-match PX4/third-party events into `px4_events`

Add a module-level pattern table and a classifier:

```python
_PX4_EVENT_PATTERNS: tuple[tuple[str, str], ...] = (
    ("arming denied", "ARMING_DENIED"),
    ("disarmed by", "DISARMED"),
    ("failsafe", "FAILSAFE"),
    ("preflight fail", "PREFLIGHT_FAIL"),
    ("emergency", "EMERGENCY"),
    ("ekf2", "EKF"),
    ("mag sensors inconsistent", "SENSOR_INCONSISTENT"),
    ("accel sensors inconsistent", "SENSOR_INCONSISTENT"),
    ("rtl", "RTL"),
    ("land detected", "LAND_DETECTED"),
    ("takeoff detected", "TAKEOFF_DETECTED"),
)

def classify_px4_line(text: str) -> str | None:
    low = text.lower()
    for needle, tag in _PX4_EVENT_PATTERNS:
        if needle in low:
            return tag
    return None
```

In `build_run_summary`'s record loop, for records that have `text` and whose
`src` is not one of our nodes (simplest robust rule: record has NO `level` and
NO `event` field - our StructuredLogger always emits one of those), run the
classifier; on a match append
`{"t": r.get("t"), "src": r.get("src"), "tag": tag, "text": <text, capped at 160 chars>}`
to a new `px4_events` list. Dedup consecutive identical `(src, text)` pairs the
same way `errors` dedups. Add `"px4_events": px4_events` to the returned dict
(and to the empty-log early return with `[]`).

The EKF needle is deliberately broad; competition debugging cares about any
EKF chatter. Cap `px4_events` at 50 entries (append a final
`{"tag": "TRUNCATED", ...}` marker if exceeded) so a pathological log cannot
bloat the summary.

**Verify**: `uv run ruff check tools/log_summary.py` -> exit 0

### Step 3: Render `px4_events` in the failure digest

In `format_failure_digest` (added by plan 033), render a `px4:` section between
`errors:` and `last events:` showing up to 8 entries as
`t=<t> [<tag>] <text>`. Omit the section when the list is empty.

**Verify**: `uv run ruff check tools/log_summary.py` -> exit 0

### Step 4: Unit tests

Add to `tests/unit/test_log_summary.py`:

- `test_px4_arming_denied_captured`: synthetic log containing
  `t=12.300 src=px4_sitl WARN [commander] Arming denied: Resolve system health failures` ->
  summary `px4_events` has one entry, tag `ARMING_DENIED`, text contains
  `Arming denied`.
- `test_px4_failsafe_captured`: a `Failsafe activated` line -> tag `FAILSAFE`.
- `test_own_node_lines_not_px4_events`: a line with `level=error` and one with
  `event=TRANSITION` produce NO `px4_events` entries (they go to
  errors/timeline as before).
- `test_px4_events_in_digest`: digest output includes the `[ARMING_DENIED]`
  line for the first case.
- `test_px4_events_cap`: 60 distinct matching lines -> 50 entries + truncation
  marker.

**Verify**: `uv run pytest tests/unit/test_log_summary.py -q` -> all pass (5 new)

### Step 5: Full gate + optional live check

**Verify**: `just check` -> exit 0. Operator (optional but recommended):
`just sim`, `just stop`, `just log summary` -> output JSON contains a
`px4_events` key (likely with TAKEOFF/LAND or EKF entries from boot).

## Test plan

Step 4's five tests: happy paths for two tags, negative case for our own
nodes, digest rendering, and the cap. Pattern: existing tests in
`tests/unit/test_log_summary.py` (synthetic logfmt text in, dict out).

## Done criteria

- [ ] `uv run pytest tests/unit/test_log_summary.py -q` passes with 5 new tests
- [ ] `rg -n "px4_events" tools/log_summary.py` shows the key in both `build_run_summary` returns and in `format_failure_digest`
- [ ] `rg -n '"text"' tools/log_summary.py` shows `parse_logfmt` preserving free text
- [ ] `just check` exits 0
- [ ] `git status` shows only in-scope files modified
- [ ] `plans/README.md` status row updated

## STOP conditions

- Plan 033 has not landed (no `format_failure_digest` in `log_summary.py`) -
  report the dependency instead of inlining a digest yourself.
- `parse_logfmt`'s structure differs from the excerpt (drift).
- Preserving `text` breaks an existing consumer of `parse_logfmt` (grep for
  other importers: `rg -n "parse_logfmt" tools/ tests/` - if any consumer
  treats unknown keys as errors, STOP).

## Maintenance notes

- The pattern table is intentionally a curated allowlist; when a new PX4
  failure string matters, add a needle + a test. Reviewers should reject
  regex-heavy generalizations - substring matching is the point.
- `tools/status.py` could surface `px4_events` in `just status` later
  (deferred; the digest and `just log summary` are the agent surfaces now).
