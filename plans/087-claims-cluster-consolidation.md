# Plan 087: Claims cluster — one roster builder, one DAG walker, one module fewer

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat d44126d..HEAD -- tools/capabilities.py tools/cap_plan.py tools/cap_status.py tasks.py tests/unit/test_capabilities.py tests/unit/test_scenario_roster.py tests/unit/test_cap_plan.py tests/unit/test_cap_status.py`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition. (Plans 084/085 also edit
> `tasks.py`; land them first or rebase — the touched regions are disjoint.)

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: LOW-MED
- **Depends on**: soft: 084, 085 first (all touch `tasks.py`; do not interleave)
- **Category**: tech-debt
- **Planned at**: commit `d44126d`, 2026-07-18

## Why this matters

The claims/capabilities cluster spends ~150 branch statements across six
tools. An audit found the layering fundamentally sound (rung derivation,
evidence IO, and formatting each live in one place), but three genuine
duplications remain: the e2e/scenario config-dict shape is built in three
near-identical loops (a sixth sim field would need three lockstep edits);
the `requires`-DAG is walked by four separate hand-rolled DFS/BFS
implementations; and `cap_plan.py` is a thin 80-line satellite of
`cap_status` that forces an awkward `from cap_plan import topo_order` back
into `capabilities.py`. Consolidating removes ~12-15 branch statements,
~100 LOC, and one module, and gives the registry one config builder and one
graph walker to maintain.

## Current state

- `tools/capabilities.py` — registry loading (`_load`), `cap` typer app,
  and three sibling iteration loops:
  - `scenarios_for_platform` (`:262-269`) — filters
    `platform in cap.get("platforms", []) and cap.get("scenario_file")`,
    returns stems. **Consumed only by tests**
    (`tests/unit/test_scenario_roster.py:7`, `tests/unit/test_capabilities.py:9`).
  - `e2e_roster` (`:279-310`) — same filter over `topo_order(data)`, skips
    entries failing `artifacts_ok`, emits
    `{"scenario", "vision", "overlay", "model", "world"}` with defaults
    `("none", "auto_arm", "x500", "default")`.
  - `scenario_sim_configs` (`:313-337`) — same filter in TOML order, emits
    the identical dict shape with the identical defaults.
  - `from cap_plan import format_plan` at `:229`, `from cap_plan import
    topo_order` at `:288` (function-local imports).
- `tools/cap_plan.py` (80 lines, full file read at `d44126d`) — imports only
  `RungInfo, display` from `cap_status`; defines `topo_order` (`:13-27`,
  recursive DFS appending dependencies-first), `next_action` (`:30-41`),
  `_closure` (`:44-56`, recursive DFS collecting the target's ancestor set),
  `format_plan` (`:59-80`).
- `tools/cap_status.py` — `derive_all`'s `rung_of` (`:113-142`) is the
  memoized rung-computing recursion (NOT a pure traversal — leave it);
  `real_artifacts_ok` ends at `:217-219` with the `mission missing` check;
  `real_mission_ok` at `:223-236`.
- `tasks.py:545-556` — `_blocked_by`: an iterative stack walk over
  `caps.get(dep, {}).get("requires", [])` returning the first ancestor found
  in `failed_claims`, else None.
- Tests: `tests/unit/test_capabilities.py`, `test_scenario_roster.py`,
  `test_cap_plan.py`, `test_cap_status.py` — the executor's safety net; all
  build synthetic registries with `tomli_w`.
- **Known-inert, deliberately out of scope**: no claim in
  `tests/capabilities.toml` sets `mission`/`params`/`source`, so
  `real_mission_ok` never runs in production. Whether to delete that path or
  wire a `mission` onto a real claim is a maintainer decision recorded in
  `plans/README.md` (Round 9 notes) — do NOT resolve it in this plan.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Full gate | `just check` (host without ROS: `distrobox enter ubuntu -- bash -lc "just check"`) | exit 0 |
| Cluster tests | `uv run pytest tests/unit/test_capabilities.py tests/unit/test_scenario_roster.py tests/unit/test_cap_plan.py tests/unit/test_cap_status.py tests/unit/test_check_capabilities.py -q` | all pass |
| CLI smoke | `uv run python tasks.py cap show` and `... cap plan` | exit 0/1 with the same table shape as before |
| Lint/type | `uv run ruff check tools/ tasks.py && uv run ty check tools/ tasks.py` | exit 0 |

## Scope

**In scope** (the only files you should modify/delete):
- `tools/capabilities.py`, `tools/cap_status.py`, `tasks.py`
- Delete: `tools/cap_plan.py`
- Tests: `tests/unit/test_capabilities.py`, `tests/unit/test_scenario_roster.py`,
  `tests/unit/test_cap_plan.py` (rename/repoint), `tests/unit/test_cap_status.py`
- `plans/README.md` (status row)

**Out of scope** (do NOT touch, even though they look related):
- `tools/cap_evidence.py`, `tools/check_capabilities.py` — evidence IO and
  registry validation stay put ( `check_capabilities._find_cycle` keeps its
  own cycle-reporting walk: it produces the error message and is the thing
  that guarantees the other walks never see a cycle).
- The rung-derivation logic (`_leaf_rung`, `derive_all`) — behavior frozen.
- `tests/capabilities.toml`, `tests/evidence/` — data, not code.
- The `mission`/`params`/`source` registry surface (see Current state).
- Output formats of `cap show` / `cap plan` — agent-facing contract.

## Git workflow

- Branch: `advisor/087-claims-consolidation`
- Conventional commits, e.g. `refactor(claims): one roster builder + cap_plan folded into cap_status`.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: One config builder in `capabilities.py`

Add one private helper and express all three loops through it:

```python
def _sim_config(entry: dict) -> dict:
    return {
        "scenario": entry["scenario_file"].removesuffix(".py"),
        "vision": entry.get("sim_vision", "none"),
        "overlay": entry.get("sim_overlay", "auto_arm"),
        "model": entry.get("sim_model", "x500"),
        "world": entry.get("sim_world", "default"),
    }

def _flyable(data: dict, platform: str):
    for name, entry in data.get("capabilities", {}).items():
        if platform in entry.get("platforms", []) and entry.get("scenario_file"):
            yield name, entry
```

- `scenario_sim_configs` → `[_sim_config(e) for _, e in _flyable(data, platform)]`.
- `e2e_roster` → iterate `topo_order(data)`, look up the entry, keep its
  current platform/scenario_file/artifacts_ok logic, but build the dict via
  `_sim_config`.
- Delete `scenarios_for_platform`; repoint its two test importers to derive
  stems from `scenario_sim_configs` (`[c["scenario"] for c in ...]`) — the
  roster assertions are unchanged.

**Verify**: cluster tests → all pass; `grep -n "sim_overlay" tools/capabilities.py`
→ exactly 1 match (inside `_sim_config`).

### Step 2: Fold `cap_plan.py` into `cap_status.py`

Move `topo_order`, `_closure` (rename to `closure`, public), `next_action`,
and `format_plan` into `cap_status.py` verbatim (they already import
`RungInfo`/`display` from there — the move removes the import). Delete
`tools/cap_plan.py`. Update importers:
- `tools/capabilities.py:229` and `:288` → import from `cap_status`.
- Rename `tests/unit/test_cap_plan.py` imports to `cap_status` (keep the
  file name and all cases).
- `grep -rn "cap_plan" tools/ tasks.py tests/` and fix every hit.

**Verify**: `uv run pytest tests/unit/test_cap_plan.py -q` → all pass;
`git ls-files tools/cap_plan.py` → empty.

### Step 3: `_blocked_by` walks the DAG via the shared `closure`

Rewrite `tasks.py:_blocked_by` to reuse the moved walker:

```python
from cap_status import closure  # with the existing tools/ path setup

def _blocked_by(registry: dict, scenario: str, failed_claims: set[str]) -> str | None:
    name = claim_for_scenario(registry, scenario)
    if name is None:
        return None
    for dep in closure(registry, name) - {name}:
        if dep in failed_claims:
            return dep
    return None
```

CAUTION: the current implementation returns the first failed ancestor in
DFS-stack order; sets are unordered. Check
`tests/unit/test_tasks_e2e_groups.py` — if any test constructs a registry
where TWO ancestors fail and pins which one is named, iterate
deterministically instead: `for dep in topo_order(registry): if dep in
closure_set and dep != name and dep in failed_claims: return dep`.

**Verify**: `uv run pytest tests/unit/test_tasks_e2e_groups.py -q` → all pass.

### Step 4: Full gate + CLI smoke

**Verify**: `just check` → exit 0; `uv run python tasks.py cap show` prints
the same rung table as on `main` (run it on `main` first and diff by eye);
`uv run python tasks.py cap plan` output unchanged for the current registry.

## Test plan

- No new behavior → no new tests except: one case in
  `tests/unit/test_capabilities.py` asserting `e2e_roster` and
  `scenario_sim_configs` produce the SAME config dict for the same entry
  (the drift this plan exists to prevent — a 5-line test).
- Keep every existing case; `test_cap_plan.py` cases move importers only.

## Done criteria

- [ ] `just check` exits 0
- [ ] `git ls-files tools/cap_plan.py` → empty
- [ ] `grep -rn "cap_plan" tools/ tasks.py tests/unit/` → no matches (test filename itself may remain)
- [ ] `grep -c "sim_overlay" tools/capabilities.py` → 1
- [ ] `grep -n "scenarios_for_platform" -r tools/ tests/` → no matches
- [ ] `cap show` / `cap plan` outputs byte-comparable to `main` for the shipped registry
- [ ] No files outside the in-scope list modified (`git status`)
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- The excerpts don't match the live code (drift — especially if 084/085
  landed with unexpected `tasks.py` changes).
- Any `cap show`/`cap plan` output difference appears for the shipped
  registry — formatting is an agent-facing contract; report the diff.
- Step 3's determinism caution turns out to matter and `topo_order`
  iteration still can't reproduce a pinned expectation.
- You are tempted to "also" delete `real_mission_ok`/the `mission` field —
  that is the maintainer decision explicitly out of scope here.

## Maintenance notes

- Deferred (recorded, not planned): consolidating the three git-show
  registry-diff call sites (`cap_evidence.changed_registry_claims` /
  `cap_status.real_changed_since` / `capabilities.record`) into one
  `registry_diff_markers` helper — touches the `cap record` freshness gate,
  wants its own careful change.
- Open maintainer decision (Round 9 index): the inert `mission`-rung path —
  either delete it (drops the `mission_ok` Callable threading through 6 call
  sites, `real_mission_ok`, and `cap_plan`'s mission branch) or make it live
  by adding `mission = "precision_land"` to that claim. Whoever resolves it
  should update `docs/CLAIMS.md` in the same change.
- Reviewer focus: Step 1 must not reorder `e2e_roster` (topo order is the
  e2e scheduling contract) and must keep the `artifacts_ok` exclusion path
  intact (`excluded` names are printed by the e2e gate).
