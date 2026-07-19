# Plan 088: check_docs — one (matcher, resolver) rule table instead of two parallel cascades

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat d44126d..HEAD -- tools/check_docs.py tests/unit/test_check_docs.py`
> If either file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P3
- **Effort**: M
- **Risk**: MED
- **Depends on**: none
- **Category**: tech-debt
- **Planned at**: commit `d44126d`, 2026-07-18

## Why this matters

`tools/check_docs.py` has the highest branch density in the repo (40 branch
statements in 175 lines). Its token taxonomy lives in two places that must
be edited in lockstep: `classify()` decides a token's kind through a 7-arm
ordered cascade, and `check_token()` re-dispatches on those same kind
strings through a second 4-arm cascade. Adding a token kind (or changing
what counts as a path) means synchronized edits to both functions. A single
ordered rule table — each rule pairing "does this token match?" with "does
it verify?" — makes the taxonomy one datum, removes ~8-10 branch statements,
and makes the checker extensible by adding a row.

## Current state

- `tools/check_docs.py` — machine-checks that backticked tokens in
  AGENTS.md/README.md/docs/*.md refer to real files, `just` recipes,
  identifiers, or topics. Constants: `_IDENT_RE` (:13), `_PATH_SUFFIXES`
  (:15), corpus config (:16-18), `_ALLOWLIST` (:21), `_SUBCOMMANDS` (:34).
- `classify` (`tools/check_docs.py:65-84`), verbatim:
  ```python
  def classify(token: str) -> str:
      if token in _ALLOWLIST or "<" in token or "[" in token or "*" in token or "&&" in token:
          return "skip"  # "<x>" and "[x]" are placeholder notation, not real tokens
      if token.startswith("just "):
          return "just"
      if token.startswith("/") and " " not in token:
          return "topic"
      if " " in token or "=" in token:
          return "skip"
      pathish = _strip_fragment(token)
      if "/" in pathish:
          suffix = Path(pathish).suffix
          if suffix in _PATH_SUFFIXES:
              return "path"
          return "skip"
      if _IDENT_RE.fullmatch(token) and "_" in token:
          return "identifier"
      return "skip"
  ```
- `check_token` (`tools/check_docs.py:126-149`): dispatches on the returned
  kind — `"path"` (exists at root, else under
  `src/core/ros_px4_template_core/`), `"just"` (recipe in `_recipes(root)`,
  optional subcommand in `_SUBCOMMANDS`), `"identifier"`/`"topic"`
  (substring of `_corpus_text(root)`), default True.
- Cached helpers `_recipes` (:87-97) and `_corpus_text` (:100-123) — keep
  as-is.
- Ordering is load-bearing: the skip-guards (allowlist/placeholder, then
  space/`=`) must be evaluated before the positive matches around them, and
  `topic` must precede the generic space/`=` skip (topics contain neither,
  but `just ...` tokens contain spaces and must be claimed first).
- Tests: `tests/unit/test_check_docs.py` covers classification and
  resolution; a kill-test tradition exists in this repo (prove the checker
  still catches a planted drift).

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| The tool itself | `uv run python tools/check_docs.py` | exit 0 on a clean tree |
| Its tests | `uv run pytest tests/unit/test_check_docs.py -q` | all pass |
| Full gate | `just check` (host without ROS: `distrobox enter ubuntu -- bash -lc "just check"`) | exit 0 |
| Branch count | `python3 -c "import ast; src=open('tools/check_docs.py').read(); print(sum(isinstance(n,(ast.If,ast.For,ast.While,ast.Try,ast.Match)) for n in ast.walk(ast.parse(src))))"` | ≤ 32 (was 40) |

## Scope

**In scope** (the only files you should modify):
- `tools/check_docs.py`
- `tests/unit/test_check_docs.py` (extend only)
- `plans/README.md` (status row)

**Out of scope** (do NOT touch, even though they look related):
- `tools/check_topics.py`, `tests/unit/test_missions_doc.py` — their
  markdown parsing is semantically different (4-column topic specs; table
  sections keyed by heading); a shared parser was considered and REJECTED
  (adds a module to save ~6 lines).
- `_ALLOWLIST`, `_SUBCOMMANDS`, `_CORPUS_DIRS` contents — data, not logic.
- Which files are checked (`_doc_files`) and the CLI/exit behavior.

## Git workflow

- Branch: `advisor/088-check-docs-rule-table`
- Conventional commit, e.g. `refactor(docs-check): single rule table for classify+verify`.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Characterize current classification (before touching logic)

Add a table-driven test case to `tests/unit/test_check_docs.py` pinning
`classify` for at least: an allowlisted token; `"<x>"`; `"just check"`;
`"just sim start"`; `"/drone/odom"`; `"a b"`; `"X=1"`;
`"docs/TOPICS.md"`; `"docs/TOPICS.md#anchor"`; `"sim/worlds"` (no suffix →
skip); `"mission_manager"`; `"CamelCase"` (no underscore → skip);
`"plain"`. Run it against the UNMODIFIED code first.

**Verify**: `uv run pytest tests/unit/test_check_docs.py -q` → all pass on
unmodified code.

### Step 2: Introduce the rule table

Replace `classify` + `check_token` with one ordered table where each entry
is `(kind, matches(token) -> bool, verify(token, root) -> bool)`; the first
matching rule wins. Skip rules use `verify = lambda *_: True`. Shape:

```python
_RULES: list[tuple[str, Callable[[str], bool], Callable[[str, Path], bool]]] = [
    ("skip", _is_placeholder, _ok),          # allowlist, <>, [], *, &&
    ("just", lambda t: t.startswith("just "), _verify_just),
    ("topic", lambda t: t.startswith("/") and " " not in t, _verify_in_corpus),
    ("skip", lambda t: " " in t or "=" in t, _ok),
    ("path", _is_pathish, _verify_path),     # "/" in stripped token + known suffix
    ("skip", lambda t: "/" in _strip_fragment(t), _ok),  # pathish, unknown suffix
    ("identifier", lambda t: bool(_IDENT_RE.fullmatch(t)) and "_" in t, _verify_in_corpus),
    ("skip", lambda t: True, _ok),
]
```

`classify(token)` becomes "first rule whose matcher hits → its kind" (keep
the function and its return values — tests and any external caller see the
same interface). `check_token(token, kind, root)` becomes a lookup that
runs the verifier of the first rule matching the token (or dispatch
kind→verifier if the call sites pass the kind they already classified —
match the existing call pattern in `main()`/`check_file`). The verifier
bodies (`_verify_path`, `_verify_just`, `_verify_in_corpus`) keep their
current logic verbatim, including the `src/core/ros_px4_template_core/`
path abbreviation and the `_SUBCOMMANDS` validation.

**Verify**: `uv run pytest tests/unit/test_check_docs.py -q` → all pass,
INCLUDING Step 1's pinned table, unmodified.

### Step 3: Kill-test + gate

Temporarily plant a fake token in a scratch copy (e.g. run the checker over
a temp README containing `` `tools/does_not_exist.py` `` and `` `just
bogus_recipe` ``) the way existing tests do — confirm both are flagged.

**Verify**: `uv run python tools/check_docs.py` → exit 0 on the real tree;
`just check` → exit 0; branch-count command → ≤ 32.

## Test plan

- Step 1's characterization table is the main addition (it survives as a
  regression net).
- Keep every existing test unchanged — if any fails after Step 2, the
  refactor changed behavior: fix the refactor, never the test.

## Done criteria

- [ ] `just check` exits 0
- [ ] Branch count of `tools/check_docs.py` ≤ 32 (was 40)
- [ ] `classify` and token verification driven by ONE `_RULES` table (grep: `_RULES` defined once; no `if kind ==` chain remains)
- [ ] Step 1 characterization test passes before AND after the refactor
- [ ] No files outside the in-scope list modified (`git status`)
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- Any pre-existing test needs its EXPECTED value changed to pass — that is a
  behavior change, not a refactor.
- The rule-table version misclassifies any token in the real docs corpus
  (diff the checker's full token/kind dump before vs after if in doubt —
  add a temporary `--dump` print locally, but do not commit it).
- Branch count lands above 34 — the table isn't paying for itself; report
  actual numbers instead of forcing it.

## Maintenance notes

- Future token kinds are now one table row + one verifier function; note
  this in the module docstring.
- Reviewer focus: rule ORDER (the two skip guards sandwiching `just`/`topic`
  — Step 1's table is the proof), and that `docs/TOPICS.md#anchor`-style
  fragments still resolve.
- Rejected in this round (recorded in the index): sharing markdown/backtick
  parsing across check_docs/check_topics/test_missions_doc — semantics
  differ, savings trivial.
