# Plan 008: `just log topics` does not false-FAIL vision topics on a non-vision sim

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat 9f5ba74..HEAD -- tools/check_topics.py docs/TOPICS.md tests/unit/test_check_topics.py`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P3
- **Effort**: S
- **Risk**: LOW
- **Depends on**: 006 (merged — the type/direction enforcement this refines)
- **Category**: dx
- **Planned at**: commit `9f5ba74`, 2026-06-21

## Why this matters

Plan 006 made `just log topics` enforce each documented topic's declared type
and direction. Verified live on 2026-06-21 it works — but on a default
(non-vision) sim it reports two false failures:
`[FAIL] /drone/marker_detection: declared pub but no publisher` and the same for
`/drone/pose_override`. Those topics are published only by the vision nodes
(`aruco_pose_publisher`, `marker_localizer`), which run only under
`--vision aruco`. On a vision-off boot their publishers legitimately do not
exist, so a tool that is supposed to catch real drift cries wolf on every
default run. (The old name-only check passed them because core nodes still
*subscribe*, so the topic appeared in `ros2 topic list`; 006 is stricter by
design.) This plan teaches the manifest to mark vision-conditional topics and
the checker to skip enforcing their presence unless vision is on — so a green
`just log topics` means something again on the common path.

## Current state

After plan 006 (merged at `218714e`), `tools/check_topics.py` has:
- `@dataclass(frozen=True) class TopicSpec: name: str; msg_type: str; direction: str`
- `parse_manifest(text) -> list[TopicSpec]` — parses the 4-column Topics table;
  `direction = cells[2].lower()` and requires it in `{"pub","sub","pub/sub"}`.
- `check_spec(spec, observed_type, pub, sub) -> list[str]` — pure verdict.
- `_live_topic_info(topic) -> (type, pub_count, sub_count)`.
- live `main()` loop: for each spec, `_live_topic_info` then `check_spec`, prints
  `[OK]`/`[FAIL]`, exits 1 if any failed.

`docs/TOPICS.md` "Topics" table rows for the two vision topics
(`docs/TOPICS.md:25-26`):
```
| `/drone/marker_detection` | `px4_ros_msgs/msg/MarkerDetection` | pub | `aruco_pose_publisher` |
| `/drone/pose_override` | `geometry_msgs/msg/PoseStamped` | pub | `marker_localizer` (known-marker relocalization fix) |
```
Live evidence (non-vision `just sim` + `just log topics`): all 12 other topics
`[OK]`; these two `[FAIL] ... declared pub but no publisher`.

`tasks.py:809-815` (`just log topics`) runs
`uv run python tools/check_topics.py --manifest docs/TOPICS.md` with no extra
flags. `tests/unit/test_check_topics.py` already covers `parse_manifest` /
`check_spec` (10 tests, post-006). Vision is enabled at the sim level with
`--vision aruco` (see `just sim` flags in `AGENTS.md`).

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Unit tests (primary gate) | `uv run pytest tests/unit/test_check_topics.py -q` | all pass incl. new cases |
| Dry-run still works | `uv run python tools/check_topics.py --manifest docs/TOPICS.md --dry-run` | lists topics, exit 0 |
| Quality gate | `just check` | exits 0 (or only the pre-existing `src/px4_msgs` gap blocks branch-invariants) |
| Live, non-vision (needs sim) | `just sim` then `just log topics` | the 2 vision topics `[SKIP]`, all others `[OK]`, exit 0 |
| Live, vision (needs sim) | `just sim --vision aruco` then `just log topics --vision` | all topics incl. the 2 vision ones `[OK]`, exit 0 |

## Scope

**In scope**:
- `tools/check_topics.py` (add a `conditional` mark to specs + a `--vision` flag
  + skip logic)
- `docs/TOPICS.md` (mark the 2 vision rows + document the marker)
- `tests/unit/test_check_topics.py` (add cases)
- `plans/README.md` (status row only — skip if a reviewer owns the index)

**Out of scope** (do NOT touch):
- The vision nodes, launch files, or `--vision` sim plumbing. This is about the
  *checker*, not when vision runs.
- `check_spec`'s existing type/direction logic — leave the verdict rules as 006
  shipped them; only gate *whether* a conditional topic is enforced.
- `tasks.py` `topics` recipe behavior beyond (optionally) accepting a
  passthrough `--vision` flag — keep the default `just log topics` non-vision.
- The other 12 topics' rows.

## Git workflow

- Branch: `advisor/008-topic-check-vision-conditional`
- Commit style: conventional commits. Suggested message:
  `feat(check-topics): skip vision-conditional topics unless --vision`.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Mark vision topics in the manifest

In `docs/TOPICS.md`, change the Dir cell for the two vision topics from `pub` to
`pub (vision)`:
- `/drone/marker_detection` row → Dir `pub (vision)`
- `/drone/pose_override` row → Dir `pub (vision)`

Add a short line under the "Topics" table (or in "Adding a topic") documenting
the marker: "A `(vision)` suffix on the Dir marks a topic published only under
`--vision aruco`; `just log topics` skips its presence check unless run with
`--vision`."

**Verify**: `rg -n "pub \(vision\)" docs/TOPICS.md` → exactly 2 matches.

### Step 2: Parse the marker into the spec

Extend `TopicSpec` with `conditional: bool = False` (keep the field optional so
existing construction sites and tests still work). In `parse_manifest`, parse the
Dir cell so a trailing `(vision)` sets `conditional=True` and the base direction
is still validated against `{"pub","sub","pub/sub"}`. For example, normalize:
strip a `(vision)` token, `.strip()`, lower-case, and record `conditional` =
whether the token was present. Non-vision rows keep `conditional=False`.

Add a tiny pure helper for the gate so it is unit-testable without a sim:
```python
def should_enforce(spec: TopicSpec, vision: bool) -> bool:
    """A conditional (vision) topic is only enforced when vision is on."""
    return vision or not spec.conditional
```

**Verify**: `uv run python -c "import sys; sys.path.insert(0,'tools'); import check_topics"` exits 0.

### Step 3: Add `--vision` and skip in live mode

Add a `--vision` boolean option to `main()` (default `False`). In the live loop,
for each spec: if `should_enforce(spec, vision)` is False, print
`  [SKIP] <name> (vision off)` and continue (do not count it as failed); else run
`_live_topic_info` + `check_spec` as today. Adjust the final summary so SKIPped
topics are not counted as failures and the success line still reflects how many
were actually checked.

Optionally let `just log topics` pass the flag through: in `tasks.py`'s `topics`
command you may add an optional `--vision` that forwards to the script. Keep the
**default** `just log topics` non-vision (so the common path is green). Only make
this `tasks.py` tweak if it stays within the one `topics` function; otherwise
leave `tasks.py` alone and document that the flag is available on the script.

**Verify**: `uv run python tools/check_topics.py --manifest docs/TOPICS.md --dry-run`
still exits 0 (dry-run unaffected).

### Step 4: Unit tests

Extend `tests/unit/test_check_topics.py`:
- `parse_manifest` on a row with Dir `pub (vision)` yields a spec with
  `direction == "pub"` and `conditional is True`; a plain `pub` row yields
  `conditional is False`.
- `should_enforce(conditional_spec, vision=False) is False`;
  `should_enforce(conditional_spec, vision=True) is True`;
  `should_enforce(plain_spec, vision=False) is True`.

**Verify**: `uv run pytest tests/unit/test_check_topics.py -q` → all pass
(existing 10 + the new cases).

### Step 5: Quality gate

**Verify**: `just check` exits 0 (or only the pre-existing missing-`src/px4_msgs`
branch-invariants gap blocks it; the lint/typecheck over `tools/` must pass).

### Step 6 (needs sim): live confirmation

```
just sim
just log topics            # 2 vision topics [SKIP], all others [OK], exit 0
just stop
just sim --vision aruco
just log topics --vision   # all topics [OK] including the 2 vision ones, exit 0
just stop
```

If you cannot run a sim, Steps 4 and 5 are the gates that must pass; report Step
6 as "pending operator sim verification".

## Test plan

- `parse_manifest` (marker parsing) and `should_enforce` (gate) are pure and are
  the decisive cheap gate — add the Step 4 cases modeled on the existing tests in
  `tests/unit/test_check_topics.py`.
- Live behavior (Step 6) is operator-verified if no sim is available.

## Done criteria

ALL must hold:

- [ ] `rg -n "pub \(vision\)" docs/TOPICS.md` returns exactly 2 matches
- [ ] `TopicSpec` has a `conditional` field; `parse_manifest` sets it from `(vision)`
- [ ] `should_enforce` exists and is unit-tested
- [ ] `--vision` flag exists on the checker; non-`--vision` live runs SKIP (not FAIL) conditional topics
- [ ] `uv run pytest tests/unit/test_check_topics.py -q` passes (10 existing + new)
- [ ] `--dry-run` still exits 0
- [ ] `just check` exits 0 (or only the pre-existing `src/px4_msgs` gap blocks it)
- [ ] No files outside the in-scope list modified (`git status`)
- [ ] `plans/README.md` status row for 008 updated (unless a reviewer owns the index)

## STOP conditions

Stop and report back (do not improvise) if:

- The two vision rows in `docs/TOPICS.md` are no longer `pub` (the manifest
  changed since this plan was written).
- Making `conditional` non-optional breaks existing `TopicSpec(...)` construction
  in tests or code — keep it defaulted; if you cannot, report why.
- On a `--vision aruco` sim, `just log topics --vision` still FAILs the two
  topics — that would be a real vision-node/manifest mismatch, a genuine finding
  for the operator, not something to skip away.

## Maintenance notes

- The `(vision)` marker generalizes: any future config-gated topic (a second
  sensor suite, an optional bridge) can reuse the pattern, and `should_enforce`
  extends to more flags if needed.
- A reviewer should confirm SKIPped topics never count toward the failure exit
  code, and that the default `just log topics` (no flag) stays green on a plain
  sim — that is the whole point.
- If many more conditional topics appear, consider a dedicated column instead of
  a Dir suffix; the suffix is the minimal change for two topics today.
