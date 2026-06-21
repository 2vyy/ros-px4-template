# Plan 006: Topic check enforces declared type and direction, not just names

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat 21cbe3d..HEAD -- tools/check_topics.py docs/TOPICS.md tasks.py`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: LOW
- **Depends on**: none
- **Category**: dx
- **Planned at**: commit `21cbe3d`, 2026-06-21

## Why this matters

`docs/TOPICS.md` already declares a **Type** and **Dir** for every topic, but
`tools/check_topics.py` only greps backticked *names* and confirms they appear
in `ros2 topic list`. So a node can publish `/drone/odom` with the wrong message
type, or a documented publisher can silently become a no-op, and the check still
passes. The manifest's own columns are unenforced documentation that will drift
the moment there is more than one contributor (the exact pain B58 names). This
plan makes the live check assert that each documented topic exists **with the
declared type and an active publisher/subscriber for its declared direction** —
turning the table from prose into a contract. QoS enforcement is deliberately
out of scope (see Maintenance notes): QoS is described in prose, not per-row
columns, and adding it is a separate manifest-schema decision.

## Current state

- `tools/check_topics.py` (87 lines). `TOPIC_RE = re.compile(r"`(/[a-zA-Z0-9_/]+)`")`
  (`:13`) pulls backticked names out of the manifest; `main()` (`:37-82`) has a
  `--dry-run` mode that greps source (`_topics_in_source`, `:16-34`) and a live
  mode that compares against `ros2 topic list` (`:68-82`). Neither looks at the
  Type or Dir columns.
- `docs/TOPICS.md` "Topics" table (`:11-26`) has the shape:
  `| Topic | Type | Dir | Owner |` with rows like
  `| \`/clock\` | \`rosgraph_msgs/msg/Clock\` | pub | clock_bridge in ... |`.
  Name and Type are backticked; Dir is plain (`pub`). A second, differently
  shaped table follows under "### Subscriptions" (`:30-39`): `| Topic | Subscribers |`
  (2 columns) — the parser must NOT treat those rows as topic specs.
- `docs/TOPICS.md:3` and `:52` still say `just check-topics`. The recipe was
  renamed to `just log topics` (see `tasks.py:809-815`, and plan 001 fixed the
  same stale name in README/AGENTS). Fix these two references here since this
  plan edits the file.
- Invocation: `just log topics` runs
  `uv run python tools/check_topics.py --manifest docs/TOPICS.md` (live mode) via
  `tasks.py:810-815`. Extending live mode is picked up automatically; **do not
  change `tasks.py`.**
- `ros2 topic info <topic>` prints, e.g.:
  ```
  Type: rosgraph_msgs/msg/Clock
  Publisher count: 1
  Subscription count: 0
  ```
  This gives both the live type and per-direction counts.

Test convention: unit tests live in `tests/unit/`, pytest, pure-logic only (no
`rclpy`/`ros2`). See `tests/unit/test_offboard_fsm.py` for the structural
pattern (module docstring, `from __future__ import annotations`, plain `def
test_*`). Keep the new parser and verdict functions pure so they unit-test the
same way; the `ros2 topic info` subprocess call stays in a thin, untested
wrapper.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Unit tests (primary gate) | `just test` | exits 0, all pass incl. new tests |
| Run unit file directly | `uv run pytest tests/unit/test_check_topics.py -q` | all pass |
| Quality gate | `just check` | exits 0, `all checks passed.` |
| Dry-run still works | `uv run python tools/check_topics.py --manifest docs/TOPICS.md --dry-run` | lists topics, exit 0 |
| Live enforcement (needs sim) | `just sim` then `just log topics` then `just stop` | all topics `OK` with type+dir |
| Confirm stale name fixed | `rg -n "check-topics" docs/TOPICS.md` | no matches |

## Scope

**In scope**:
- `tools/check_topics.py` (add manifest-row parsing + type/direction live check)
- `tests/unit/test_check_topics.py` (create)
- `docs/TOPICS.md` (fix `check-topics` to `log topics` on lines 3 and 52; update
  the "Adding a topic" note to say type+dir are enforced)
- `plans/README.md` (status row only — skip if a reviewer owns the index)

**Out of scope** (do NOT touch):
- `tasks.py` — the `topics` recipe already invokes the checker correctly.
- The `--dry-run` source-grep mode behavior — it cannot see types; leave it
  name-only. You may reuse the new parser to get names, but its pass/fail stays
  as today (names found in source).
- QoS. Do not parse the "## QoS" prose or add a QoS column; that is a separate
  schema decision (Maintenance notes).
- Any node or the manifest's actual rows/values. You are enforcing the existing
  declarations, not changing them.

## Git workflow

- Branch: `advisor/006-enforce-topic-types`
- Commit style: conventional commits. Suggested message:
  `feat(check-topics): enforce declared type and direction, not just names`.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Add a pure manifest-row parser and verdict function

In `tools/check_topics.py`, add (keep the existing `TOPIC_RE` for backward
compatibility / dry-run names):

```python
from dataclasses import dataclass

@dataclass(frozen=True)
class TopicSpec:
    name: str
    msg_type: str
    direction: str  # "pub" | "sub" | "pub/sub"

_CELL_BACKTICK = re.compile(r"`([^`]+)`")
_VALID_DIRS = {"pub", "sub", "pub/sub"}

def parse_manifest(text: str) -> list[TopicSpec]:
    """Parse the 4-column Topics table rows into specs. Rows that are not a
    topic spec (headers, separators, the 2-column Subscriptions table) are
    skipped, so this is safe to run over the whole file."""
    specs: list[TopicSpec] = []
    for line in text.splitlines():
        s = line.strip()
        if not s.startswith("|"):
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if len(cells) != 4:
            continue
        name_m = _CELL_BACKTICK.search(cells[0])
        type_m = _CELL_BACKTICK.search(cells[1])
        direction = cells[2].lower()
        if not name_m or not type_m or direction not in _VALID_DIRS:
            continue
        if not name_m.group(1).startswith("/"):
            continue
        specs.append(TopicSpec(name_m.group(1), type_m.group(1), direction))
    return specs

def check_spec(spec: TopicSpec, observed_type: str | None, pub: int, sub: int) -> list[str]:
    """Pure verdict: return a list of problem strings ([] means OK)."""
    if observed_type is None:
        return ["not present on the live graph"]
    problems: list[str] = []
    if observed_type != spec.msg_type:
        problems.append(f"type {observed_type} != declared {spec.msg_type}")
    if "pub" in spec.direction and pub < 1:
        problems.append("declared pub but no publisher")
    if "sub" in spec.direction and sub < 1:
        problems.append("declared sub but no subscriber")
    return problems
```

**Verify**: `uv run python -c "import tools.check_topics"` exits 0 (module
imports; run from repo root).

### Step 2: Add the live `ros2 topic info` wrapper and wire it into live mode

Add a thin subprocess wrapper (kept out of unit tests):

```python
def _live_topic_info(topic: str) -> tuple[str | None, int, int]:
    """(msg_type, publisher_count, subscription_count) from `ros2 topic info`."""
    result = subprocess.run(
        ["ros2", "topic", "info", topic], capture_output=True, text=True
    )
    if result.returncode != 0:
        return None, 0, 0
    msg_type: str | None = None
    pub = sub = 0
    for raw in result.stdout.splitlines():
        ln = raw.strip()
        if ln.startswith("Type:"):
            msg_type = ln.split(":", 1)[1].strip()
        elif ln.startswith("Publisher count:"):
            pub = int(ln.split(":", 1)[1].strip() or 0)
        elif ln.startswith("Subscription count:"):
            sub = int(ln.split(":", 1)[1].strip() or 0)
    return msg_type, pub, sub
```

In `main()`'s **live** branch (the non-`dry_run` path, currently `:68-82`),
replace the name-only comparison with: parse specs via `parse_manifest(text)`,
and for each spec call `_live_topic_info` then `check_spec`. Print
`  [OK] <name>` when problems is empty, else `  [FAIL] <name>: <problems joined>`.
Track whether any spec failed; at the end print a count and
`raise typer.Exit(1)` if any failed, else echo
`All N documented topics match (type + direction).`. Keep the manifest read
(`text = manifest.read_text(...)`) and the empty-manifest guard
(`:49-53`) intact.

**Verify**: `uv run python tools/check_topics.py --manifest docs/TOPICS.md --dry-run`
still lists topics and exits 0 (dry-run path unchanged).

### Step 3: Unit tests

Create `tests/unit/test_check_topics.py`, modeled on
`tests/unit/test_offboard_fsm.py`. Cover at least:

- `parse_manifest` on a small inline manifest returns the right specs (name,
  msg_type, direction) for a 4-column row.
- `parse_manifest` **skips** a 2-column Subscriptions-style row and the header /
  separator rows (assert those names are absent from the result).
- `check_spec` happy path: matching type + publisher present for `pub` returns `[]`.
- `check_spec` type mismatch returns a problem mentioning both types.
- `check_spec` declared `pub` with `pub=0` returns the "no publisher" problem.
- `check_spec` with `observed_type=None` returns the "not present" problem.

**Verify**: `uv run pytest tests/unit/test_check_topics.py -q` → all pass.

### Step 4: Fix the stale recipe name + document enforcement in TOPICS.md

- `docs/TOPICS.md:3`: `just check-topics` becomes `just log topics`.
- `docs/TOPICS.md:52` (step 3 of "Adding a topic"): `just check-topics` becomes
  `just log topics`.
- In "Adding a topic", update the wording so it states the Type and Dir columns
  are now enforced live (so contributors know to fill them correctly), e.g. add:
  "The Type and Dir columns are enforced by `just log topics` against the live
  graph, so they must match the node's actual publisher/subscriber and message
  type."

**Verify**: `rg -n "check-topics" docs/TOPICS.md` returns no matches.

### Step 5: Quality gate

**Verify**: `just check` exits 0 and ends with `all checks passed.`

### Step 6 (DECISIVE, needs full sim env): live enforcement

```
just sim
just log topics
just stop
```

**Verify**: every documented topic prints `[OK]` and the summary line reports a
type+direction match. A `[FAIL]` here means either a real manifest/node
mismatch (a genuine find — report it, do not "fix" the manifest to make it pass)
or a parser bug.

If you cannot run the sim (no `PX4_DIR`, non-Linux, no Gazebo), Steps 3 and 5
are the gates that must pass; complete them, then STOP and report Step 6 as
"pending operator sim verification" rather than marking the plan fully done.

## Test plan

- New file `tests/unit/test_check_topics.py` with the six+ cases in Step 3,
  modeled on `tests/unit/test_offboard_fsm.py`.
- The parser and `check_spec` are pure, so the unit tests are the primary,
  cheap, decisive gate. The `_live_topic_info` subprocess wrapper is thin and
  not unit-tested; it is exercised by the Step 6 live run.
- Verification: `just test` exits 0 with the new tests passing.

## Done criteria

ALL must hold:

- [ ] `parse_manifest`, `check_spec`, `_live_topic_info`, `TopicSpec` exist in `tools/check_topics.py`
- [ ] `uv run pytest tests/unit/test_check_topics.py -q` passes (>= 6 tests)
- [ ] `rg -n "check-topics" docs/TOPICS.md` returns no matches
- [ ] `--dry-run` mode still exits 0 on the current manifest
- [ ] `just check` exits 0
- [ ] Live `just log topics` reports type+direction match (or Step 6 reported "pending operator sim verification")
- [ ] No files outside the in-scope list are modified (`git status`)
- [ ] `plans/README.md` status row for 006 updated (unless a reviewer owns the index)

## STOP conditions

Stop and report back (do not improvise) if:

- `tests/unit/test_check_topics.py` already exists with unrelated content (do
  not overwrite — report it).
- The "Topics" table shape in `docs/TOPICS.md` is no longer `| Topic | Type | Dir | Owner |`
  (the parser assumptions break).
- Live `just log topics` reports a type/direction mismatch that is a real
  node-vs-manifest discrepancy. That is a genuine finding for the operator, not
  something to paper over by editing the manifest — report which topic and the
  observed vs declared values.
- `ros2 topic info` output format differs from the `Type:` / `Publisher count:`
  / `Subscription count:` lines assumed in Step 2.

## Maintenance notes

- **QoS is the deliberate follow-up.** It is described in the "## QoS" prose,
  not per-row, so enforcing it needs a manifest-schema decision (add a QoS
  column, or a structured per-topic block). Do that as a separate plan; this one
  stops at type + direction, which the existing columns already support.
- A reviewer should confirm the parser ignores the Subscriptions table and any
  future prose tables (the `len(cells) == 4` + backticked-name+type guard is
  what protects this), and that the live check fails closed (a missing topic or
  a `ros2 topic info` error counts as a failure, not a pass).
- If a topic is legitimately both published and subscribed, set Dir to `pub/sub`
  in the manifest; `check_spec` already handles that.
