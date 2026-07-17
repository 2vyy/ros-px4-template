# Plan 060: Close the doc-drift holes — MISSIONS.md tables machine-checked, schema-regen friction removed, check_docs widened, stale MCP block fixed

> **Executor instructions**: Follow this plan step by step, verifying each
> step. On any STOP condition, stop and report. When done, update
> `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 01f94c7..HEAD -- tools/check_docs.py docs/MISSIONS.md AGENTS.md tools/mission_cli.py tests/unit/test_check_docs.py tests/unit/test_mission_schema.py tasks.py`
> On any mismatch with the excerpts below, STOP.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: MED only for part C (widening check_docs will surface benign
  tokens needing allowlist tuning); others LOW
- **Depends on**: none
- **Category**: dx / docs
- **Planned at**: commit `01f94c7`, 2026-07-10

## Why this matters

Plan 047 built `tools/check_docs.py` to end the doc-drift bug class, but four
holes remain, each of which costs an agent a wasted cycle:

- **A.** The `docs/MISSIONS.md` Behaviors/Guards tables are hand-maintained
  with no drift check — a new behavior passes `just check` (the JSON schema
  auto-includes it) while the human-facing contract table stays silently
  incomplete. This is the exact drift plan 022 killed for the schema,
  relocated to the prose.
- **B.** The "Adding a behavior or guard" checklist omits the mandatory
  schema regeneration; the agent discovers it via a guaranteed
  `just check` failure whose message names the command but not the redirect
  target. Predictable extra edit→fail→search→re-check cycle on a core workflow.
- **C.** `check_docs.py` reads ONLY `AGENTS.md`, only checks forward
  existence, and `just <recipe> <subcmd>` validates only the recipe — a wrong
  command in `README.md` or `docs/MISSIONS.md` (the files agents actually
  follow) passes.
- **D.** The `AGENTS.md` tail instructs agents to use `search_graph` /
  `trace_path` / `get_code_snippet` / `query_graph` / `get_architecture` from
  a "codebase-memory-mcp" that this environment does not expose (the
  available graph tool is CodeGraph's `codegraph_explore`), and
  `check_docs.py` ALLOWLISTS those five names, making the drift structurally
  invisible to the checker.

## Current state

- `tools/check_docs.py:126` — `text = (root / "AGENTS.md").read_text(...)`;
  `:20-29` — allowlist of the five MCP tool names with the comment
  "codebase-memory MCP tool"; `:64` — identifiers require `_` (single-word
  names like `hold` classify as `skip`); `:110-113` — `just X ...` checks
  only `X` against justfile recipes.
- `docs/MISSIONS.md:106-118` — Behaviors table (rows: `hold`,
  `follow_waypoints`, `search_lawnmower`, `center_on_marker`, `center_land`,
  `goto_origin`); `:123-146` — Guards table (15 rows); `:235-244` — the
  3-step "Adding a behavior or guard" checklist (write function, unit test,
  reference from YAML — no schema step).
- `tests/unit/test_mission_schema.py` asserts committed
  `schemas/mission.schema.json == build_schema()`; its failure message names
  `just mission schema` but not the `> schemas/mission.schema.json` redirect
  (the full incantation lives only at `docs/MISSIONS.md:71`).
- Registry access (rclpy-free): `tools/mission_cli.py:22-26` shows the
  import pattern (`sys.path.insert` of `src/core`, then
  `from ros_px4_template_core.lib.mission.registry import known_behaviors, known_guards`).
- `AGENTS.md` tail: a "## Rules" block (fff/gh/rtk lines) and a
  "# Codebase Knowledge Graph (codebase-memory-mcp)" section listing the five
  tools with priority order and examples. The repo root HAS a `.codegraph/`
  index, and the CLAUDE.md-level guidance already tells agents to use
  CodeGraph — the codebase-memory block is stale boilerplate from a different
  tool.

## Commands you will need

| Purpose | Command | Expected |
|---------|---------|----------|
| Quality gate | `just check` | exit 0 (includes the docs step) |
| Docs check alone | `uv run python tools/check_docs.py` | `Docs identifier check OK: ...` |
| Docs check verbose | `uv run python tools/check_docs.py --verbose` | lists SKIP tokens (for allowlist tuning) |
| Targeted tests | `uv run pytest tests/unit/test_check_docs.py tests/unit/test_missions_doc.py -q` | all pass |
| Schema regen | `just mission schema > schemas/mission.schema.json` | file unchanged today |

## Scope

**In scope**:
- `tools/check_docs.py` and `tests/unit/test_check_docs.py`
- `docs/MISSIONS.md` (checklist step; no table content changes unless the new
  test exposes a genuinely missing row)
- `AGENTS.md` (replace the codebase-memory block; checklist pointer)
- `tests/unit/test_missions_doc.py` (new)
- `tests/unit/test_mission_schema.py` (assertion message only)

**Out of scope**:
- `tools/mission_cli.py` `build_schema` and the schema file itself
- Making `just check` auto-regenerate the schema in place (tempting, but
  silently rewriting a committed file during `check` changes the gateway's
  contract — the owner deferred this; improve the MESSAGE instead)
- `docs/superpowers/` archives (already excluded from the corpus, `:91-92`)

## Git workflow

- Branch: `advisor/060-doc-drift-net`
- Commit per part (A-D), style: `test(docs): MISSIONS.md tables must cover the live registry`, etc.

## Steps

### Part A: registry ↔ MISSIONS.md table test

New `tests/unit/test_missions_doc.py` (import the registry the way
`tools/mission_cli.py:22-26` does, or rely on `tests/conftest.py`'s path
setup — check which exists for unit tests; `test_mission_engine.py` imports
`ros_px4_template_core.lib.mission` directly, so conftest already handles it):

```python
import re
from pathlib import Path

from ros_px4_template_core.lib import mission as _m  # noqa: F401  (registers all)
from ros_px4_template_core.lib.mission.registry import known_behaviors, known_guards

DOC = Path(__file__).resolve().parents[2] / "docs" / "MISSIONS.md"


def _table_names(text: str, heading: str) -> set[str]:
    section = text.split(f"## {heading}", 1)[1].split("\n## ", 1)[0]
    return set(re.findall(r"^\| `([a-z_]+)` \|", section, flags=re.M))


def test_every_behavior_documented() -> None:
    names = _table_names(DOC.read_text(encoding="utf-8"), "Behaviors")
    missing = known_behaviors() - names
    assert not missing, f"add a row to docs/MISSIONS.md Behaviors table for: {sorted(missing)}"


def test_every_guard_documented() -> None:
    names = _table_names(DOC.read_text(encoding="utf-8"), "Guards")
    missing = known_guards() - names
    assert not missing, f"add a row to docs/MISSIONS.md Guards table for: {sorted(missing)}"


def test_no_phantom_rows() -> None:
    text = DOC.read_text(encoding="utf-8")
    phantom = (_table_names(text, "Behaviors") - known_behaviors()) | (
        _table_names(text, "Guards") - known_guards()
    )
    assert not phantom, f"docs/MISSIONS.md documents names not in the registry: {sorted(phantom)}"
```

Adjust `_table_names` to the file's actual row format (`| `name` | ... |`) —
read the tables and confirm the regex matches all current rows before
trusting a green run (count: 6 behaviors, 15 guards at `01f94c7`).

**Verify**: `uv run pytest tests/unit/test_missions_doc.py -q` → 3 passed.
Kill-test: temporarily delete the `goto_origin` row → first test fails naming
it; restore.

### Part B: checklist + message

- `docs/MISSIONS.md:235-244`: add steps 4-5 to the checklist:
  `4. Regenerate the editor schema: just mission schema > schemas/mission.schema.json`
  `5. Add a row to the Behaviors/Guards table above (a unit test enforces this).`
- `tests/unit/test_mission_schema.py`: extend the drift assertion message to
  the full incantation `just mission schema > schemas/mission.schema.json`.
- `AGENTS.md` "Code changes" mission bullet: append "then regenerate the
  schema and add the MISSIONS.md table row (unit-enforced)."

**Verify**: `just check` → exit 0.

### Part C: widen check_docs

In `tools/check_docs.py`:

1. Check `README.md` and every `docs/*.md` (top level only, skip
   `docs/superpowers/`) in addition to `AGENTS.md`: wrap the per-file loop,
   report failures as `[FAIL] <file>: <token> (<kind>)`.
2. Validate `just <recipe> <subcmd>` second tokens for the sub-app recipes:
   build the known sub-command sets by parsing `tasks.py` is over-engineering —
   instead hardcode a dict in check_docs with a comment, sourced from the
   typer sub-apps: `{"log": {"summary", "tail", "topics"}, "cap": {"show",
   "mark"}, "mission": {"list", "validate", "show", "schema"}, "test":
   {"unit", "e2e", "scenario"}}` and only check membership when the recipe is
   a key (flags starting `-` stay exempt as today, `:111-112`). Grep
   `tasks.py` for the current sub-commands before writing the dict
   (plan 054, if landed, adds `mission sim`).
3. Delete the five codebase-memory allowlist entries (Part D removes their
   uses). Keep `C:\`.
4. Run `--verbose` over the widened corpus and add any genuinely-benign new
   SKIP-worthy tokens to the allowlist WITH a reason comment each (expect a
   handful from README/SKEIN.md: URLs already skip via `/` + suffix rules;
   tune only what actually fails).

Extend `tests/unit/test_check_docs.py` (11 tests exist; follow its fixture
style): multi-file failure attribution; sub-command validation
(`just log frobnicate` fails, `just log tail` passes, `just sim --gui`
passes).

**Verify**: `uv run python tools/check_docs.py` → OK over the widened corpus
(fix any REAL drift it finds in the docs as part of this plan — list each fix
in the commit message); `uv run pytest tests/unit/test_check_docs.py -q` →
all pass.

### Part D: replace the stale MCP block in AGENTS.md

Replace the "# Codebase Knowledge Graph (codebase-memory-mcp)" section
(from its heading to the end of its Examples list) with a short CodeGraph
note consistent with the repo's actual tooling:

```markdown
# Code intelligence

The repo is indexed by CodeGraph (`.codegraph/`). For structural questions
(callers, definitions, blast radius), prefer `codegraph explore "<symbols or
question>"` (shell) or the `codegraph_explore` MCP tool over grep + file
reads. Fall back to `rg`/file reads for string literals, configs, and
non-code files.
```

Keep the "## Rules" block above it (fff/gh/rtk lines) — those tools exist in
the maintainer's environment; only the codebase-memory section is stale.

**Verify**: `uv run python tools/check_docs.py` → OK (the five names are gone
from both the doc and the allowlist); `grep -n "search_graph\|codebase-memory" AGENTS.md tools/check_docs.py`
→ no matches.

## Done criteria

- [ ] `test_missions_doc.py` 3 tests pass; kill-test demonstrated
- [ ] MISSIONS.md checklist has the schema-regen + table-row steps; schema test message includes the redirect
- [ ] check_docs covers README.md + docs/*.md, validates the sub-command dict, and its allowlist has no codebase-memory entries
- [ ] AGENTS.md tail describes CodeGraph, not codebase-memory-mcp
- [ ] `just check` exit 0 end to end
- [ ] `plans/README.md` row updated

## STOP conditions

- Widened check_docs surfaces >10 failing tokens across README/docs — the
  corpus rules need design attention, not allowlist whack-a-mole; report the
  list.
- The MISSIONS.md tables use a row format the regex can't capture uniformly —
  adjust the regex to the actual format; if the tables are structurally
  inconsistent between the two sections, normalize the DOC format (cosmetic)
  rather than complicating the parser.
- The maintainer's global tooling genuinely provides `search_graph` etc.
  (check: does the environment list a codebase-memory MCP server?) — then
  Part D becomes "verify and document which is canonical" — STOP and ask
  rather than deleting.

## Maintenance notes

- The sub-command dict in check_docs is a deliberate, commented hardcode —
  when a typer sub-app gains a command, the docs check fails on the new doc
  line until the dict learns it. Cheap, visible, single-file.
- Part A's test makes plan 062/063's new behaviors self-enforcing: their
  MISSIONS.md rows can't be forgotten.
