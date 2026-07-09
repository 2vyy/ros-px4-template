# Plan 047: Machine-check AGENTS.md against the codebase (end the doc-drift bug class)

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report - do not improvise. When done, update the status row for this plan
> in `plans/README.md` - unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat ead4cc6..HEAD -- AGENTS.md tasks.py tools/`
> Plan 035 MUST have landed (it fixes the currently-stale AGENTS.md rows this
> checker would flag on day one). Plans 031/033/037/039/045 legitimately edit
> `tasks.py` - reconcile. Any other drift vs excerpts is a STOP condition.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: LOW-MED (a checker that cries wolf gets deleted; the design below is deliberately conservative)
- **Depends on**: plans/035-agent-docs-accuracy.md (must be DONE first)
- **Category**: dx
- **Planned at**: commit `ead4cc6`, 2026-07-06

## Why this matters

This is the third occurrence of the same bug class: plans 001, 017, and 035
each fixed agent-facing docs naming identifiers that no longer exist
(deleted nodes, renamed phases, wrong flags, wrong defaults). Wrong docs are
worse than missing docs for an autonomous agent - AGENTS.md's "If X fails"
table is the FIRST thing consulted on a failure, and a dead identifier costs
a full wrong-hypothesis loop. Prose that duplicates machine-knowable facts
will drift again; the fix is to make the prose a checked artifact. This plan
adds a conservative existence checker for AGENTS.md's backticked identifiers
and wires it into `just check`.

## Design (deliberately narrow - resist expanding it)

Check ONE property: every backticked token in `AGENTS.md` that LOOKS like a
code identifier must still exist somewhere in the repo. No semantic checks,
no value checks (a wrong default like "3s" is out of scope - that class is
rarer and needs human judgment).

Classification of each `` `token` `` extracted from AGENTS.md:

1. **Checkable - file path**: contains `/` and ends in a known extension
   (`.py .md .yaml .toml .sdf .json .sh .rviz`) or is a path that exists ->
   check `Path(token).exists()` relative to repo root. Strip trailing
   line/anchor fragments (`#...`).
2. **Checkable - just command**: starts with `just ` -> the first word after
   `just` must appear as a recipe in `justfile` (parse recipe names: lines
   matching `^[a-z_-]+.*:` at column 0, minus `_`-prefixed).
3. **Checkable - plain identifier**: matches `^[A-Za-z_][A-Za-z0-9_.]*$` AND
   contains `_` (underscore is the strong signal for a code identifier;
   single plain words like `unit`, `summary`, `map` are skipped as prose) ->
   must appear in the codebase:
   `rg -q --fixed-strings <token>` over `src/ tools/ tests/ config/ sim/ hardware/ docs/ justfile tasks.py`
   (exclude `plans/`, `docs/superpowers/` - historical archives may
   legitimately be the only mention of an old name, which must NOT count as
   alive; excluding them also means they cannot keep a dead name "alive").
4. **Checkable - ROS topic**: starts with `/` and contains no space ->
   `rg -q --fixed-strings` over the same set (all real topics appear in
   `docs/TOPICS.md` at minimum).
5. **Everything else** (flags with spaces, shell snippets, env-var
   assignments, wildcards): SKIP. False negatives are acceptable; false
   positives are what kills adoption.

Plus a small allowlist constant in the script for legitimately-unmatchable
tokens (e.g. `` `C:\` ``, placeholder names like `<NN>_<name>`); tokens
containing `<` or `*` are auto-skipped.

## Current state

- `AGENTS.md` - the target document (CLAUDE.md is a symlink to it; check
  AGENTS.md only). After plan 035 it should be fully green under the rules
  above.
- `tools/` conventions: typer apps, pure logic in testable functions,
  `tests/conftest.py` puts `tools/` on `sys.path`, exemplar test file
  `tests/unit/test_wait_ready.py`.
- `tasks.py check` (lines 390-457): sequential gate steps, each appending to
  `failed_steps` - the invariants step (lines 414-419,
  `uv run python tools/check_invariants.py`) is the wiring pattern to copy.
- `just check` is expected to stay fast; this check is pure grep/filesystem,
  well under a second.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Run the checker | `uv run python tools/check_docs.py` | `[OK]` lines + exit 0 on a clean AGENTS.md |
| Unit tests | `uv run pytest tests/unit/test_check_docs.py -q` | all pass |
| Full gate | `just check` | exit 0, now including the docs step |

## Scope

**In scope**:
- `tools/check_docs.py` (create)
- `tests/unit/test_check_docs.py` (create)
- `tasks.py` (one new step in `check`, after invariants, before typecheck)
- `AGENTS.md` (ONLY if the checker finds real stragglers 035 missed - fix the
  doc, never weaken the checker to pass)

**Out of scope**:
- `README.md`, `docs/*.md` - start with the one file agents read first;
  extending coverage is a follow-up once the false-positive rate is proven
  ~zero on AGENTS.md.
- Semantic/value checking (defaults, counts, behavior descriptions).
- Checking that code identifiers are DOCUMENTED (reverse direction).

## Git workflow

- Branch: `advisor/047-docs-drift-check`
- Commit style: `feat(check): verify AGENTS.md backticked identifiers exist in the codebase`
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: `tools/check_docs.py`

Structure (pure functions + thin main, per repo convention):

- `extract_backticked(text: str) -> list[str]` - regex `` `([^`\n]+)` ``,
  dedup preserving order.
- `classify(token: str) -> str` - returns one of
  `"path" | "just" | "identifier" | "topic" | "skip"` per the Design rules.
- `check_token(token: str, kind: str, root: Path) -> bool` - the existence
  checks. For grep-kinds, ONE `subprocess.run(["rg", "-q", "--fixed-strings",
  token, <paths...>])` per token is fine at this scale (AGENTS.md has ~120
  backticked tokens, most skipped); if you prefer zero subprocesses, read the
  target files once into a single string and use `in` - either is acceptable,
  pick one and keep it simple.
- `main()` - reads `AGENTS.md`, prints one `[OK] <token>` /
  `[FAIL] <token> (<kind>): not found` line per CHECKED token (match
  `tools/preflight.py`'s `[OK]`/`[FAIL]` style), summary verdict line, exit
  0/1. `--verbose` may list skipped tokens; default output stays short.
- `_ALLOWLIST: frozenset[str]` at module top with a comment saying additions
  require a reason string next to each entry.

**Verify**: `uv run python tools/check_docs.py` -> exit 0 against the
post-035 AGENTS.md. If it exits 1, inspect each `[FAIL]`: real drift -> fix
AGENTS.md; misclassification -> tighten `classify` (or allowlist with a
reason), and note it in your report.

### Step 2: Unit tests

`tests/unit/test_check_docs.py`, pure (feed strings/tmp_path, no repo
dependence):

1. `extract_backticked` pulls tokens, dedups, ignores triple-backtick fences'
   interiors is NOT required (tokens inside code fences are still fine to
   check or skip - pick the simpler behavior and pin it with this test).
2. `classify`: `src/core/x.py` -> path; `just sim` -> just; `marker_hover` ->
   identifier; `/drone/odom` -> topic; `unit` -> skip; `--vision aruco` ->
   skip; `<NN>_<name>` -> skip.
3. `check_token` path-kind against `tmp_path` (exists/missing).
4. identifier-kind found/not-found against a synthetic corpus.
5. An end-to-end `main`-level test: tiny AGENTS.md in `tmp_path` with one
   dead identifier -> exit code 1 and `[FAIL]` in output (use
   `capsys`/`monkeypatch` per `test_wait_ready.py` patterns).

**Verify**: `uv run pytest tests/unit/test_check_docs.py -q` -> all pass

### Step 3: Wire into `just check`

In `tasks.py` `check`, after the invariants step (copy its shape):

```python
    print("Checking agent docs identifiers...")
    res = subprocess.run(
        ["uv", "run", "python", "tools/check_docs.py"], cwd=str(ROOT), env=env
    )
    if res.returncode != 0:
        failed_steps.append("docs identifiers")
```

**Verify**: `uv run ruff check tasks.py tools/check_docs.py` -> exit 0;
`just check` -> exit 0 with the new step visible in output.

### Step 4: Prove it catches the bug class

Temporarily add a line to AGENTS.md referencing a dead identifier (e.g.
`` `sim_pose_adapter` `` - the exact ghost plan 035 exorcised), run
`uv run python tools/check_docs.py` -> exit 1 naming it. Revert the line.

**Verify**: the FAIL fired and the revert leaves `git diff AGENTS.md` empty.

## Test plan

Step 2's five unit tests (extraction, classification table, both check
kinds, end-to-end exit code) plus Step 4's live kill-test against the actual
document. The checker's own false-positive rate on the real AGENTS.md is the
Step 1 acceptance gate.

## Done criteria

- [ ] `uv run python tools/check_docs.py` exits 0 on current AGENTS.md
- [ ] Step 4 kill-test flagged the planted dead identifier
- [ ] `uv run pytest tests/unit/test_check_docs.py -q` -> all pass
- [ ] `rg -n "check_docs" tasks.py` -> wired into `check` between invariants and typecheck
- [ ] `just check` exits 0
- [ ] `git status` shows only in-scope files modified
- [ ] `plans/README.md` status row updated

## STOP conditions

- Plan 035 has not landed and the checker reports its known stale rows - do
  not fix AGENTS.md here beyond stragglers; report the ordering problem.
- More than ~5 tokens need allowlisting on the real AGENTS.md - the
  classifier is too eager; report the token list instead of growing the
  allowlist past the point of meaninglessness.
- `rg` is unavailable in the gate environment (if you chose the subprocess
  route) - switch to the in-Python `in` scan rather than adding a dependency.

## Maintenance notes

- Extending to `README.md`/`docs/` is a param away (`--file`, default
  AGENTS.md) once trust is earned - do not do it preemptively.
- The failure mode to watch in review: someone allowlisting a token instead
  of fixing the doc. Each allowlist entry requires an inline reason.
- This closes the loop that plans 001/017/035 fixed manually; if a fourth
  drift round happens AFTER this lands, the classifier missed a kind - add
  the kind, with a test.
