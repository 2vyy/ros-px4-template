# Plan 074: Claims ladder core — derived capability rungs, committed evidence, `cap show/record/plan`

> **For agentic workers:** execute task-by-task with the checkbox steps; run
> every Verify and confirm the expected result before the next step. Spec:
> `docs/superpowers/specs/2026-07-17-claims-ladder-design.md` (read it first;
> it is the authority on semantics). If anything in "STOP conditions" occurs,
> stop and report. Update this plan's row in `plans/README.md` when done.
>
> **Drift check (run first)**:
> `git diff --stat 5c1124f..HEAD -- tools/capabilities.py tests/capabilities.toml tasks.py justfile tests/unit/test_capabilities.py tests/unit/test_scenario_roster.py AGENTS.md docs/`
> On any mismatch with the "Current state" excerpts below, STOP.

**Goal:** replace the hand-stamped capability registry with a claims ladder:
rungs (`declared` -> `simulated` -> `sim-flown`) DERIVED from committed
evidence with commit-based staleness, a `requires` DAG, and three commands
(`cap show`, `cap record`, `cap plan`) that a background agent can loop on.

**Architecture:** `tests/capabilities.toml` stays the single registry (form
validated in `just check`); `tests/evidence/<claim>/*.json` is the committed
PASS ledger; three new pure tools modules (`check_capabilities`,
`cap_evidence`, `cap_status`, `cap_plan`) compose into the existing
`tools/capabilities.py` typer app that tasks.py already mounts as `just cap`.

**Tech stack:** Python 3.12, tomllib/tomli_w, typer, pytest; uv; ruff + ty
gate everything via `just check`. All commands run inside distrobox.

## Status

- **Priority**: P1
- **Effort**: L
- **Risk**: MED (deletes `cap mark`, migrates the registry schema; e2e keeps
  working because `scenario_sim_configs` is untouched in this plan)
- **Depends on**: none (069/070 are independent; 075 integrates with them)
- **Category**: direction / feature
- **Planned at**: commit `5c1124f`, 2026-07-17
- **Absorbs**: plan 067's registry-validator and scaffold-snippet items
  (067 is retired; its `--overlay` CLI validation moved to plan 068)

## Global constraints

- House style: no em dashes, no Unicode arrows in committed docs/code.
- `lib/` and `src/` stay test-registry blind: nothing under `src/` may read
  `tests/capabilities.toml`.
- Every CLI ends with an English verdict; exit codes 0 success / 1 fail /
  2 usage / 3 precondition (`tools/cli_verdict.py` conventions).
- Unit tests import tools modules directly (tools/ is on the test path; see
  `tests/unit/test_capabilities.py:9` `from capabilities import ...`).
- Rung order (fixed vocabulary): `declared` < `simulated` <
  `sim-flown-stale` < `sim-flown`. Display form of the third:
  `sim-flown (stale, since <commit>)`.
- Flight-relevant paths (one definition, used by staleness AND dirty-tree
  checks): `src/`, `sim/`, `config/`, plus the claim's own
  `tests/scenarios/<scenario_file>`.

## Current state

- `tools/capabilities.py` (90 lines, read it fully): typer app with `show`
  (lines 28-34, prints stored `status`) and `mark` (lines 37-48, setdefaults
  an entry and stamps `status = "verified"` + `last_verified`); pure readers
  `scenarios_for_platform` (51-58) and `scenario_sim_configs` (61-85) that
  the e2e harness consumes. `_load`/`_save` helpers (17-25).
- `tasks.py:198,208`: `from capabilities import app as cap_app` ...
  `app.add_typer(cap_app, name="cap", ...)` -- new subcommands added to the
  typer app in `tools/capabilities.py` are automatically `just cap <cmd>`.
- `tasks.py` `check()` (lines ~572-645): ordered steps (ruff, invariants,
  check_docs, ty, build, pytest) using a `failed_steps` list pattern -- the
  registry validator becomes one more step.
- `tasks.py:1266-1273` (`scenario_new`): prints a registry snippet including
  `status = "unverified"` -- breaks once `status` is gone; updated here.
- `tests/capabilities.toml`: 8 entries, each with `status`,
  `last_verified`, `platforms`, `scenario_file`, `sim_*` fields (see file).
- `tests/unit/test_capabilities.py`: 5 tests pinning the pure readers (some
  fixtures carry `status` keys -- harmless leftovers, readers ignore them).
- `tests/unit/test_scenario_roster.py`: bijection tests between scenario
  files and registry entries.
- `just cap mark` documented in AGENTS.md (Tooling table, workflows table,
  Verify table, "Code changes" bullet) and README; `check_docs` (plan 047)
  machine-checks backticked identifiers, so stale references fail the gate.
- Evidence durability today: none -- `logs/scenario_*.json` is gitignored.
- `logs/` is gitignored; `tests/` is tracked (new `tests/evidence/` will be
  committed).
- Artifact locations for the `simulated` rung: overlays
  `config/params/overlays/<name>.yaml`; worlds `sim/worlds/<name>.sdf`;
  repo models `sim/models/<name>/` (`x500` is PX4-shipped, always valid);
  vision values `none` | `aruco`; missions `config/missions/<name>.yaml`,
  dry-run via `uv run python tools/mission_cli.py sim <name>` (exit 0 =
  reaches terminal).

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Quality gate | `just check` | exit 0 |
| One test file | `uv run pytest tests/unit/test_check_capabilities.py -q` | all pass |
| Validator solo | `uv run python tools/check_capabilities.py` | exit 0, verdict line |
| Derived status | `just cap show` | table + verdict |
| Frontier | `just cap plan` | actions or LADDER COMPLETE |

## Scope

**In scope**: `tools/check_capabilities.py` (new), `tools/cap_evidence.py`
(new), `tools/cap_status.py` (new), `tools/cap_plan.py` (new),
`tools/capabilities.py`, `tests/capabilities.toml`, `tasks.py` (check step +
scenario_new snippet), `tests/evidence/` (new dir), `tests/unit/` (new +
updated tests), `AGENTS.md`, `docs/CLAIMS.md` (new), `README.md` (only if it
names `cap mark` -- grep first).

**Out of scope** (do NOT touch): `scenario_sim_configs` /
`scenarios_for_platform` behavior (e2e contract -- plan 075 evolves the
roster); mission YAML/loader (075); e2e ordering/auto-record (075);
`src/` anything; skein.

## Git workflow

- Branch: `advisor/074-claims-ladder-core`
- Commit per task (messages given in each task). Do NOT push unless told.

---

### Task 1: Registry validator (`tools/check_capabilities.py`)

**Files:**
- Create: `tools/check_capabilities.py`
- Test: `tests/unit/test_check_capabilities.py`

**Interfaces:**
- Produces: `validate_registry(data: dict) -> list[str]` (error strings,
  empty = valid) and `main() -> None` (prints errors, verdict line, exit 1
  on errors / 0 clean). Task 2 wires `main` into `just check`; tasks 4-6
  assume a valid registry shape.

- [ ] **Step 1: Write the failing tests**

```python
"""tests/unit/test_check_capabilities.py"""
from __future__ import annotations

from check_capabilities import validate_registry


def _entry(**kw: object) -> dict:
    base: dict = {"description": "d", "platforms": ["sim"]}
    base.update(kw)
    return base


def test_valid_registry_returns_no_errors() -> None:
    data = {
        "capabilities": {
            "arm_takeoff": _entry(scenario_file="01_arm_takeoff.py", requires=[]),
            "challenge": {"description": "d", "requires": ["arm_takeoff"]},
        }
    }
    assert validate_registry(data) == []

def test_unknown_requires_id_is_named() -> None:
    data = {"capabilities": {"a": _entry(scenario_file="s.py", requires=["ghost"])}}
    errs = validate_registry(data)
    assert len(errs) == 1 and "a" in errs[0] and "ghost" in errs[0]

def test_cycle_is_rejected() -> None:
    data = {
        "capabilities": {
            "a": _entry(scenario_file="a.py", requires=["b"]),
            "b": _entry(scenario_file="b.py", requires=["a"]),
        }
    }
    assert any("cycle" in e for e in validate_registry(data))

def test_composite_with_empty_requires_is_rejected() -> None:
    data = {"capabilities": {"c": {"description": "d", "requires": []}}}
    assert any("composite" in e for e in validate_registry(data))

def test_leaf_without_platforms_is_rejected() -> None:
    data = {"capabilities": {"a": {"description": "d", "scenario_file": "a.py"}}}
    assert any("platforms" in e for e in validate_registry(data))

def test_unknown_platform_value_is_rejected() -> None:
    data = {"capabilities": {"a": _entry(scenario_file="a.py", platforms=["moon"])}}
    assert any("moon" in e for e in validate_registry(data))

def test_wrong_field_types_are_rejected() -> None:
    data = {"capabilities": {"a": _entry(scenario_file="a.py", requires="arm")}}
    assert any("requires" in e and "list" in e for e in validate_registry(data))

def test_legacy_status_field_is_rejected() -> None:
    data = {"capabilities": {"a": _entry(scenario_file="a.py", status="verified")}}
    assert any("status" in e and "derived" in e for e in validate_registry(data))
```

- [ ] **Step 2: Run, confirm failure**

Run: `uv run pytest tests/unit/test_check_capabilities.py -q`
Expected: import error (`check_capabilities` not found).

- [ ] **Step 3: Implement**

```python
#!/usr/bin/env python3
"""tools/check_capabilities.py -- FORM validation for tests/capabilities.toml.

Runs inside `just check`. Rejects malformed claims: unknown/cyclic
`requires`, empty-requires composites, bad types, unknown platforms, and
the retired stored-status fields. Artifact EXISTENCE is deliberately not
checked here: missing artifacts hold a claim at `declared` (cap_status);
a claim must be addable before its scenario exists.
"""
from __future__ import annotations

import sys
import tomllib
from pathlib import Path

KNOWN_PLATFORMS = ("sim", "hw")
REGISTRY = Path(__file__).resolve().parents[1] / "tests" / "capabilities.toml"
_STR_FIELDS = ("description", "scenario_file", "mission", "source",
               "sim_vision", "sim_overlay", "sim_model", "sim_world")


def _has_cycle(caps: dict) -> bool:
    state: dict[str, int] = {}  # 0 visiting, 1 done

    def visit(node: str) -> bool:
        if state.get(node) == 0:
            return True
        if state.get(node) == 1 or node not in caps:
            return False
        state[node] = 0
        hit = any(visit(dep) for dep in caps[node].get("requires", []))
        state[node] = 1
        return hit

    return any(visit(n) for n in caps)


def validate_registry(data: dict) -> list[str]:
    errs: list[str] = []
    caps = data.get("capabilities", {})
    for name, entry in caps.items():
        for legacy in ("status", "last_verified"):
            if legacy in entry:
                errs.append(
                    f"{name}: field '{legacy}' is retired -- rungs are derived "
                    "(delete it; see docs/CLAIMS.md)"
                )
        if not isinstance(entry.get("description", ""), str) or not entry.get("description"):
            errs.append(f"{name}: 'description' (non-empty string) is required")
        req = entry.get("requires", [])
        if not (isinstance(req, list) and all(isinstance(r, str) for r in req)):
            errs.append(f"{name}: 'requires' must be a list of claim ids")
            req = []
        for dep in req:
            if dep not in caps:
                errs.append(f"{name}: requires unknown claim '{dep}' (add it or fix the id)")
        is_leaf = "scenario_file" in entry
        if not is_leaf and not req:
            errs.append(f"{name}: composite claim (no scenario_file) must have non-empty 'requires'")
        if is_leaf:
            plats = entry.get("platforms")
            if not (isinstance(plats, list) and plats):
                errs.append(f"{name}: leaf claim needs non-empty 'platforms'")
            else:
                for p in plats:
                    if p not in KNOWN_PLATFORMS:
                        errs.append(f"{name}: unknown platform '{p}' (known: {KNOWN_PLATFORMS})")
        for f in _STR_FIELDS:
            if f in entry and not isinstance(entry[f], str):
                errs.append(f"{name}: '{f}' must be a string")
        if "params" in entry and not isinstance(entry["params"], dict):
            errs.append(f"{name}: 'params' must be a table")
    if _has_cycle(caps):
        errs.append("requires graph has a cycle -- claims must form a DAG")
    return errs


def main() -> None:
    data = tomllib.loads(REGISTRY.read_text(encoding="utf-8"))
    errs = validate_registry(data)
    for e in errs:
        print(f"  [FAIL] {e}", file=sys.stderr)
    n = len(data.get("capabilities", {}))
    if errs:
        print(f"REGISTRY INVALID: {len(errs)} error(s) in {REGISTRY.name}", file=sys.stderr)
        raise SystemExit(1)
    print(f"REGISTRY OK: {n} claims, DAG valid")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests, confirm pass**

Run: `uv run pytest tests/unit/test_check_capabilities.py -q` -> all pass.

- [ ] **Step 5: Commit**

`git add tools/check_capabilities.py tests/unit/test_check_capabilities.py`
`git commit -m "feat(cap): registry form validator (claims ladder)"`

### Task 2: Migrate the registry; wire validator into `just check`; delete `cap mark`

**Files:**
- Modify: `tests/capabilities.toml` (all 8 entries)
- Modify: `tasks.py` (`check()` step; `scenario_new` snippet at ~1266-1273)
- Modify: `tools/capabilities.py` (delete `mark`, delete unused imports)
- Modify: `tests/unit/test_capabilities.py` (drop `status` from fixtures)
- Modify: `AGENTS.md` (ONLY the `cap mark` occurrences, minimal edit so
  `just check`'s check_docs stays green; full docs rewrite is Task 7)

**Interfaces:**
- Produces: the migrated registry schema every later task reads;
  `requires` edges as below.

- [ ] **Step 1: Migrate `tests/capabilities.toml`**

For every entry: DELETE `status` and `last_verified`; ADD `requires`:

| claim | requires |
|-------|----------|
| arm_takeoff | `[]` |
| hover_hold | `["arm_takeoff"]` |
| waypoint_nav | `["arm_takeoff"]` |
| aruco_hover | `["arm_takeoff"]` |
| search_relocalize | `["waypoint_nav", "aruco_hover"]` |
| yaw_control | `["arm_takeoff"]` |
| precision_land | `["aruco_hover"]` |
| aruco_hover_real | `["aruco_hover"]` |

Keep every other field byte-identical (descriptions, scenario_file, sim_*).

- [ ] **Step 2: Wire the validator into `check()`**

In `tasks.py` `check()`, after the invariants step and following the
`failed_steps` pattern used by the neighboring steps:

```python
print("Validating claims registry...")
res = subprocess.run(
    ["uv", "run", "python", "tools/check_capabilities.py"], cwd=str(ROOT)
)
if res.returncode != 0:
    failed_steps.append("claims registry")
```

(Match the exact local style of the surrounding steps -- read them first.)

- [ ] **Step 3: Delete `mark`; update the scaffold snippet**

- `tools/capabilities.py`: delete the `mark` command (lines 37-48) and the
  now-unused `from datetime import date`; keep `_save` (Task 3 does not use
  it, but `tomli_w` import goes if nothing else uses it -- check).
- `tasks.py` `scenario_new` snippet: the printed example entry becomes:

```python
print(f"[capabilities.{cap_id}]")
print(f'description = "TODO one-line claim"')
print('requires = ["arm_takeoff"]')
print(f'scenario_file = "{name}.py"')
print('platforms = ["sim"]')
print('sim_vision = "none"')
print('sim_overlay = "auto_arm"')
print('sim_world = "default"')
print('sim_model = "x500"')
```

- `AGENTS.md`: replace `just cap mark <id> sim` occurrences with
  `just cap record <id>` (grep: `rg -n "cap mark" AGENTS.md README.md`).
- `tests/unit/test_capabilities.py`: remove `status` keys from fixtures.

- [ ] **Step 4: Verify**

Run: `uv run python tools/check_capabilities.py` -> `REGISTRY OK: 8 claims, DAG valid`.
Run: `uv run pytest tests/unit/test_capabilities.py tests/unit/test_scenario_roster.py -q` -> pass.
Run: `rg -n "cap mark" tools/ tasks.py AGENTS.md README.md justfile` -> no matches.
Run: `just check` -> exit 0 (validator step green; `just cap record` is not
documented as existing yet anywhere check_docs validates commands -- if
check_docs flags it, defer the AGENTS.md text swap to Task 5 and note it).

- [ ] **Step 5: Commit**

`git commit -am "feat(cap): migrate registry to claims schema; validator in just check; retire cap mark"`

### Task 3: Evidence ledger (`tools/cap_evidence.py`)

**Files:**
- Create: `tools/cap_evidence.py`
- Test: `tests/unit/test_cap_evidence.py`
- Create: `tests/evidence/.gitkeep`

**Interfaces:**
- Produces:
  - `FLIGHT_PATHS: tuple[str, ...] = ("src/", "sim/", "config/")`
  - `flight_relevant(paths: list[str], scenario_file: str | None) -> list[str]`
    (subset of `paths` that are flight-relevant for a claim)
  - `build_record(claim: str, platform: str, commit: str, report: dict, conditions: dict) -> dict`
  - `write_record(record: dict, root: Path, keep: int = 3) -> Path` (writes
    `<root>/<claim>/<utc YYYYMMDD_HHMMSS>_<platform>.json`, prunes oldest
    beyond `keep` per claim+platform)
  - `load_records(root: Path, claim: str) -> list[dict]` (newest first;
    unreadable JSON skipped with a stderr warning naming the file)
- Consumes: scenario report shape from `tests/scenarios/_common.py`
  `write_report` (`{"scenario", "passed", "elapsed_s", "detail"}`).

- [ ] **Step 1: Write the failing tests**

```python
"""tests/unit/test_cap_evidence.py"""
from __future__ import annotations

import json
from pathlib import Path

from cap_evidence import build_record, flight_relevant, load_records, write_record

_REPORT = {"scenario": "08_precision_land", "passed": True, "elapsed_s": 141.2,
           "detail": {"xy_err": 0.06}}


def test_build_record_shape() -> None:
    rec = build_record("precision_land", "sim", "5c1124f", _REPORT,
                       {"world": "default", "model": "x500", "vision": "aruco"})
    assert set(rec) == {"claim", "platform", "commit", "run_id", "verdict",
                        "elapsed_s", "detail", "conditions", "grade"}
    assert rec["verdict"] == "PASS" and rec["grade"] is None
    assert rec["detail"] == {"xy_err": 0.06}

def test_write_prunes_to_keep(tmp_path: Path) -> None:
    for i in range(5):
        rec = build_record("c", "sim", f"c{i}", _REPORT, {})
        rec["run_id"] = f"2026071{i}_000000"  # distinct filenames
        write_record(rec, tmp_path, keep=3)
    files = sorted((tmp_path / "c").glob("*.json"))
    assert len(files) == 3

def test_load_records_newest_first_and_skips_corrupt(tmp_path: Path, capsys) -> None:
    d = tmp_path / "c"; d.mkdir()
    (d / "20260101_000000_sim.json").write_text(json.dumps({"commit": "old"}))
    (d / "20260201_000000_sim.json").write_text(json.dumps({"commit": "new"}))
    (d / "20260301_000000_sim.json").write_text("{not json")
    recs = load_records(tmp_path, "c")
    assert [r["commit"] for r in recs] == ["new", "old"]

def test_flight_relevant_filters() -> None:
    changed = ["src/core/x.py", "docs/README.md", "tests/scenarios/08_precision_land.py",
               "tests/scenarios/01_arm_takeoff.py", "plans/074.md"]
    hit = flight_relevant(changed, "08_precision_land.py")
    assert hit == ["src/core/x.py", "tests/scenarios/08_precision_land.py"]
```

- [ ] **Step 2: Run, confirm import failure**, then **Step 3: Implement**

```python
#!/usr/bin/env python3
"""tools/cap_evidence.py -- committed PASS-evidence ledger for the claims ladder.

One small JSON per passing run under tests/evidence/<claim>/. PASS only:
failures stay in logs; the ledger measures proven capability. See
docs/CLAIMS.md.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

FLIGHT_PATHS: tuple[str, ...] = ("src/", "sim/", "config/")
EVIDENCE_ROOT = Path(__file__).resolve().parents[1] / "tests" / "evidence"


def flight_relevant(paths: list[str], scenario_file: str | None) -> list[str]:
    scen = f"tests/scenarios/{scenario_file}" if scenario_file else None
    return [p for p in paths if p.startswith(FLIGHT_PATHS) or p == scen]


def build_record(claim: str, platform: str, commit: str, report: dict,
                 conditions: dict) -> dict:
    return {
        "claim": claim,
        "platform": platform,
        "commit": commit,
        "run_id": datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S"),
        "verdict": "PASS" if report.get("passed") else "FAIL",
        "elapsed_s": report.get("elapsed_s", 0.0),
        "detail": report.get("detail", {}),
        "conditions": conditions,
        "grade": None,
    }


def write_record(record: dict, root: Path = EVIDENCE_ROOT, keep: int = 3) -> Path:
    d = root / record["claim"]
    d.mkdir(parents=True, exist_ok=True)
    out = d / f"{record['run_id']}_{record['platform']}.json"
    out.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    same = sorted(p for p in d.glob(f"*_{record['platform']}.json"))
    for old in same[:-keep]:
        old.unlink()
    return out


def load_records(root: Path, claim: str) -> list[dict]:
    d = root / claim
    if not d.is_dir():
        return []
    recs = []
    for p in sorted(d.glob("*.json"), reverse=True):
        try:
            recs.append(json.loads(p.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            print(f"[cap_evidence] WARN: unreadable evidence skipped: {p}", file=sys.stderr)
    return recs
```

- [ ] **Step 4: Run tests** -> all pass. Also `touch tests/evidence/.gitkeep`.
- [ ] **Step 5: Commit**: `git add -A && git commit -m "feat(cap): committed evidence ledger"`

### Task 4: Rung derivation (`tools/cap_status.py`) + derived `cap show`

**Files:**
- Create: `tools/cap_status.py`
- Test: `tests/unit/test_cap_status.py`
- Modify: `tools/capabilities.py` (`show` command)

**Interfaces:**
- Produces:
  - `RUNG_ORDER = ("declared", "simulated", "sim-flown-stale", "sim-flown")`
  - `@dataclass RungInfo: rung: str; reason: str = ""; evidence: dict | None = None`
  - `derive_all(data: dict, records: dict[str, list[dict]], changed_since: Callable[[str], list[str] | None], artifacts_ok: Callable[[dict], tuple[bool, str]], mission_ok: Callable[[str], tuple[bool, str]]) -> dict[str, RungInfo]`
    -- pure; `changed_since(commit)` returns changed paths vs HEAD or `None`
    if the commit is unknown; `artifacts_ok(entry)` / `mission_ok(name)`
    return `(ok, why_not)`.
  - `display(info: RungInfo) -> str` (e.g. `sim-flown (stale, since 9d12d49)`)
  - `real_changed_since(commit: str) -> list[str] | None`,
    `real_artifacts_ok(entry: dict) -> tuple[bool, str]`,
    `real_mission_ok(name: str) -> tuple[bool, str]` -- the impure defaults
    (git diff, filesystem, `uv run python tools/mission_cli.py sim <name>`
    via subprocess).
- Consumes: Task 3's `load_records`/`flight_relevant`; Task 1's valid shape.

- [ ] **Step 1: Write the failing tests** (pure path only; fakes injected)

```python
"""tests/unit/test_cap_status.py"""
from __future__ import annotations

from cap_status import RUNG_ORDER, RungInfo, derive_all, display

_OK = lambda *_: (True, "")           # noqa: E731
_NO = lambda *_: (False, "missing")   # noqa: E731


def _reg(**caps: dict) -> dict:
    return {"capabilities": caps}


def _leaf(**kw: object) -> dict:
    e: dict = {"description": "d", "platforms": ["sim"],
               "scenario_file": "01_arm_takeoff.py", "requires": []}
    e.update(kw)
    return e


def _ev(commit: str = "aaa") -> dict:
    return {"claim": "a", "platform": "sim", "commit": commit, "verdict": "PASS",
            "run_id": "20260717_000000", "elapsed_s": 1.0, "detail": {},
            "conditions": {}, "grade": None}


def test_declared_when_artifacts_missing() -> None:
    out = derive_all(_reg(a=_leaf()), {}, lambda c: [], _NO, _OK)
    assert out["a"].rung == "declared" and "missing" in out["a"].reason

def test_simulated_when_artifacts_ok_no_evidence() -> None:
    out = derive_all(_reg(a=_leaf()), {}, lambda c: [], _OK, _OK)
    assert out["a"].rung == "simulated"

def test_sim_flown_with_fresh_evidence() -> None:
    out = derive_all(_reg(a=_leaf()), {"a": [_ev()]}, lambda c: [], _OK, _OK)
    assert out["a"].rung == "sim-flown"

def test_stale_when_flight_paths_changed() -> None:
    out = derive_all(_reg(a=_leaf()), {"a": [_ev("aaa")]},
                     lambda c: ["src/core/x.py"], _OK, _OK)
    assert out["a"].rung == "sim-flown-stale"
    assert "aaa" in display(out["a"])

def test_stale_when_commit_unknown() -> None:
    out = derive_all(_reg(a=_leaf()), {"a": [_ev()]}, lambda c: None, _OK, _OK)
    assert out["a"].rung == "sim-flown-stale" and "commit_unknown" in out["a"].reason

def test_doc_only_change_stays_fresh() -> None:
    out = derive_all(_reg(a=_leaf()), {"a": [_ev()]},
                     lambda c: ["docs/README.md"], _OK, _OK)
    assert out["a"].rung == "sim-flown"

def test_mission_failing_holds_at_declared() -> None:
    out = derive_all(_reg(a=_leaf(mission="hover")), {}, lambda c: [], _OK, _NO)
    assert out["a"].rung == "declared" and "missing" in out["a"].reason

def test_composite_is_min_of_requires() -> None:
    reg = _reg(
        a=_leaf(),
        b=_leaf(scenario_file="02_hover_hold.py", requires=["a"]),
        top={"description": "d", "requires": ["a", "b"]},
    )
    recs = {"a": [_ev()], "b": []}
    out = derive_all(reg, recs, lambda c: [], _OK, _OK)
    assert out["a"].rung == "sim-flown" and out["b"].rung == "simulated"
    assert out["top"].rung == "simulated"  # min of closure

def test_rung_order_is_total() -> None:
    assert RUNG_ORDER == ("declared", "simulated", "sim-flown-stale", "sim-flown")
```

- [ ] **Step 2: Run, confirm failure**, then **Step 3: Implement**

```python
#!/usr/bin/env python3
"""tools/cap_status.py -- derive claim rungs from evidence. Never stored.

declared:  entry valid (check_capabilities) but artifacts missing/failing
simulated: scenario file + overlay/world/model resolve; mission sim passes
sim-flown: newest sim PASS evidence, no flight-relevant diff vs HEAD
stale:     evidence exists but flight-relevant paths changed (or commit gone)
Composites (no scenario_file): min rung of their requires closure.
"""
from __future__ import annotations

import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from cap_evidence import flight_relevant

RUNG_ORDER = ("declared", "simulated", "sim-flown-stale", "sim-flown")
ROOT = Path(__file__).resolve().parents[1]


@dataclass
class RungInfo:
    rung: str
    reason: str = ""
    evidence: dict | None = None


def display(info: RungInfo) -> str:
    if info.rung == "sim-flown-stale":
        commit = (info.evidence or {}).get("commit", "?")
        return f"sim-flown (stale, since {commit})"
    return info.rung


def _leaf_rung(entry: dict, recs: list[dict],
               changed_since: Callable[[str], list[str] | None],
               artifacts_ok: Callable[[dict], tuple[bool, str]],
               mission_ok: Callable[[str], tuple[bool, str]]) -> RungInfo:
    ok, why = artifacts_ok(entry)
    if ok and entry.get("mission"):
        ok, why = mission_ok(entry["mission"])
    if not ok:
        return RungInfo("declared", reason=why)
    passes = [r for r in recs if r.get("verdict") == "PASS" and r.get("platform") == "sim"]
    if not passes:
        return RungInfo("simulated")
    ev = passes[0]
    changed = changed_since(ev["commit"])
    if changed is None:
        return RungInfo("sim-flown-stale", reason="commit_unknown", evidence=ev)
    hits = flight_relevant(changed, entry.get("scenario_file"))
    if hits:
        return RungInfo("sim-flown-stale", reason=f"changed: {', '.join(hits[:3])}", evidence=ev)
    return RungInfo("sim-flown", evidence=ev)


def derive_all(data: dict, records: dict[str, list[dict]],
               changed_since: Callable[[str], list[str] | None],
               artifacts_ok: Callable[[dict], tuple[bool, str]],
               mission_ok: Callable[[str], tuple[bool, str]]) -> dict[str, RungInfo]:
    caps = data.get("capabilities", {})
    out: dict[str, RungInfo] = {}

    def rung_of(name: str) -> RungInfo:
        if name in out:
            return out[name]
        entry = caps[name]
        if "scenario_file" in entry:
            info = _leaf_rung(entry, records.get(name, []),
                              changed_since, artifacts_ok, mission_ok)
        else:
            # Guard unknown deps so cap show stays usable on a mid-edit
            # registry (just check is the loud gate; this is the quiet one).
            childs = [rung_of(dep) for dep in entry.get("requires", []) if dep in caps]
            if not childs:
                info = RungInfo("declared", reason="requires unknown claims (run just check)")
            else:
                lowest = min(childs, key=lambda i: RUNG_ORDER.index(i.rung))
                info = RungInfo(lowest.rung, reason="composite: min of requires")
        out[name] = info
        return info

    for name in caps:
        rung_of(name)
    return out


# ---- impure defaults (composed by the CLI; not unit-tested directly) ----

def real_changed_since(commit: str) -> list[str] | None:
    res = subprocess.run(["git", "diff", "--name-only", f"{commit}..HEAD"],
                         cwd=str(ROOT), capture_output=True, text=True)
    if res.returncode != 0:
        return None
    return [line for line in res.stdout.splitlines() if line]


def real_artifacts_ok(entry: dict) -> tuple[bool, str]:
    missing: list[str] = []
    scen = entry.get("scenario_file", "")
    if not (ROOT / "tests" / "scenarios" / scen).is_file():
        missing.append(f"scenario missing: tests/scenarios/{scen}")
    overlay = entry.get("sim_overlay", "auto_arm")
    if not (ROOT / "config" / "params" / "overlays" / f"{overlay}.yaml").is_file():
        missing.append(f"overlay missing: {overlay}")
    world = entry.get("sim_world", "default")
    if not (ROOT / "sim" / "worlds" / f"{world}.sdf").is_file():
        missing.append(f"world missing: {world}")
    model = entry.get("sim_model", "x500")
    if model != "x500" and not (ROOT / "sim" / "models" / model).is_dir():
        missing.append(f"model missing: {model}")
    if entry.get("sim_vision", "none") not in ("none", "aruco"):
        missing.append(f"unknown vision: {entry['sim_vision']}")
    if entry.get("mission") and not (
        ROOT / "config" / "missions" / f"{entry['mission']}.yaml"
    ).is_file():
        missing.append(f"mission missing: {entry['mission']}")
    return (not missing, "; ".join(missing))


def real_mission_ok(name: str) -> tuple[bool, str]:
    res = subprocess.run(
        ["uv", "run", "python", "tools/mission_cli.py", "sim", name],
        cwd=str(ROOT), capture_output=True, text=True)
    if res.returncode == 0:
        return True, ""
    return False, f"mission sim failing: {name} (run: just mission sim {name})"
```

NOTE for the executor: check `tools/mission_cli.py`'s actual sim subcommand
invocation (`sim <name>` vs a flag) with `uv run python tools/mission_cli.py --help`
and match it; adjust `real_mission_ok` if it differs.

- [ ] **Step 4: Rewire `show`**

In `tools/capabilities.py`, replace the `show` body:

```python
@app.command()
def show() -> None:
    """Derived rung per claim (never stored). See docs/CLAIMS.md."""
    from cap_evidence import EVIDENCE_ROOT, load_records
    from cap_status import derive_all, display, real_artifacts_ok, real_changed_since, real_mission_ok

    data = _load()
    caps = data.get("capabilities", {})
    records = {name: load_records(EVIDENCE_ROOT, name) for name in caps}
    infos = derive_all(data, records, real_changed_since, real_artifacts_ok, real_mission_ok)
    flown = 0
    for name, info in infos.items():
        age = ""
        if info.evidence:
            age = f"  evidence {info.evidence['run_id']} @ {info.evidence['commit']}"
        note = f"  ({info.reason})" if info.reason and info.rung != "sim-flown" else ""
        typer.echo(f"{name:<22} {display(info):<32}{age}{note}")
        flown += info.rung == "sim-flown"
    typer.echo(f"CLAIMS: {flown}/{len(infos)} sim-flown (derived, not stored)")
```

- [ ] **Step 5: Verify + commit**

Run: `uv run pytest tests/unit/test_cap_status.py -q` -> pass.
Run: `just cap show` -> 8 rows; with no evidence yet, expect every leaf at
`simulated` (all artifacts exist) and the summary `0/8 sim-flown`.
`git commit -am "feat(cap): derived rung engine + derived cap show"`

### Task 5: `cap record`

**Files:**
- Modify: `tools/capabilities.py` (new command)
- Test: extend `tests/unit/test_cap_evidence.py`

**Interfaces:**
- Produces: `just cap record <claim>` -- exit 0 recorded / 2 unknown claim /
  3 precondition (no fresh PASS report, or dirty flight-relevant tree).
- Consumes: Task 3 ledger; `logs/scenario_<stem>.json`.

- [ ] **Step 1: Failing test for the pure precondition helper**

Add to `tools/cap_evidence.py` a pure helper and test it:

```python
def dirty_flight_paths(porcelain: str, scenario_file: str | None) -> list[str]:
    """Flight-relevant paths from `git status --porcelain` output."""
    paths = [line[3:].strip() for line in porcelain.splitlines() if line.strip()]
    return flight_relevant(paths, scenario_file)
```

```python
def test_dirty_flight_paths_filters_porcelain() -> None:
    from cap_evidence import dirty_flight_paths
    porcelain = " M src/core/x.py\n?? docs/notes.md\n M tests/scenarios/01_arm_takeoff.py\n"
    assert dirty_flight_paths(porcelain, "01_arm_takeoff.py") == [
        "src/core/x.py", "tests/scenarios/01_arm_takeoff.py"]
```

- [ ] **Step 2: Implement the command** in `tools/capabilities.py`:

```python
@app.command()
def record(claim: str) -> None:
    """File PASS evidence for CLAIM from its latest scenario report."""
    import json
    import subprocess

    from cap_evidence import EVIDENCE_ROOT, build_record, dirty_flight_paths, write_record

    data = _load()
    entry = data.get("capabilities", {}).get(claim)
    if entry is None or "scenario_file" not in entry:
        typer.echo(f"NO SUCH LEAF CLAIM: {claim} (see just cap show)", err=True)
        raise typer.Exit(2)
    stem = entry["scenario_file"].removesuffix(".py")
    report_path = Path("logs") / f"scenario_{stem}.json"
    if not report_path.exists():
        typer.echo(f"NO REPORT: run `just scenario {stem}` first ({report_path} missing)", err=True)
        raise typer.Exit(3)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if not report.get("passed"):
        typer.echo(f"REPORT IS A FAIL: evidence records PASSes only ({report_path})", err=True)
        raise typer.Exit(3)
    porcelain = subprocess.run(["git", "status", "--porcelain"],
                               capture_output=True, text=True).stdout
    dirty = dirty_flight_paths(porcelain, entry["scenario_file"])
    if dirty:
        typer.echo("DIRTY TREE: commit flight-relevant changes first: "
                   + ", ".join(dirty[:5]), err=True)
        raise typer.Exit(3)
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                            capture_output=True, text=True).stdout.strip()
    conditions = {"world": entry.get("sim_world", "default"),
                  "model": entry.get("sim_model", "x500"),
                  "vision": entry.get("sim_vision", "none")}
    rec = build_record(claim, "sim", commit, report, conditions)
    out = write_record(rec, EVIDENCE_ROOT)
    typer.echo(f"RECORDED {claim} sim PASS @ {commit} -> {out} (commit the file)")
```

- [ ] **Step 3: Verify + commit**

Run: `uv run pytest tests/unit/test_cap_evidence.py -q` -> pass.
Smoke: `uv run python tools/capabilities.py record ghost_claim` -> exit 2.
`git commit -am "feat(cap): cap record files committed PASS evidence"`

### Task 6: `cap plan` (`tools/cap_plan.py`)

**Files:**
- Create: `tools/cap_plan.py`
- Test: `tests/unit/test_cap_plan.py`
- Modify: `tools/capabilities.py` (new command)

**Interfaces:**
- Produces: `topo_order(data: dict) -> list[str]` (dependencies first,
  registry order among ties); `next_action(name: str, entry: dict, info: RungInfo) -> str`;
  `format_plan(data, infos, target: str | None) -> tuple[str, bool]`
  (text, ladder_complete). CLI `just cap plan [claim]` exits 0 iff complete.
- Consumes: Task 4's `RungInfo`/`derive_all`/`display`.

- [ ] **Step 1: Failing tests**

```python
"""tests/unit/test_cap_plan.py"""
from __future__ import annotations

from cap_plan import format_plan, next_action, topo_order
from cap_status import RungInfo


def _reg() -> dict:
    return {"capabilities": {
        "arm_takeoff": {"description": "d", "platforms": ["sim"],
                        "scenario_file": "01_arm_takeoff.py", "requires": []},
        "rover_follow": {"description": "d", "platforms": ["sim"],
                         "scenario_file": "10_rover_follow.py",
                         "requires": ["arm_takeoff"]},
        "challenge_2": {"description": "d", "requires": ["rover_follow"]},
    }}


def test_topo_order_puts_dependencies_first() -> None:
    order = topo_order(_reg())
    assert order.index("arm_takeoff") < order.index("rover_follow") < order.index("challenge_2")

def test_next_action_scaffold_when_scenario_missing() -> None:
    entry = _reg()["capabilities"]["rover_follow"]
    act = next_action("rover_follow", entry, RungInfo("declared", reason="scenario missing: tests/scenarios/10_rover_follow.py"))
    assert act == "just scenario-new 10_rover_follow"

def test_next_action_mission_sim_when_mission_failing() -> None:
    entry = {"description": "d", "scenario_file": "s.py", "mission": "hover", "requires": []}
    act = next_action("x", entry, RungInfo("declared", reason="mission sim failing: hover (run: just mission sim hover)"))
    assert act == "just mission sim hover"

def test_next_action_fly_when_simulated_or_stale() -> None:
    entry = _reg()["capabilities"]["arm_takeoff"]
    assert next_action("arm_takeoff", entry, RungInfo("simulated")) == "just scenario 01_arm_takeoff"
    assert next_action("arm_takeoff", entry, RungInfo("sim-flown-stale")) == "just scenario 01_arm_takeoff"

def test_format_plan_complete_when_all_flown() -> None:
    infos = {n: RungInfo("sim-flown") for n in _reg()["capabilities"]}
    text, complete = format_plan(_reg(), infos, None)
    assert complete and "LADDER COMPLETE" in text

def test_format_plan_scopes_to_target_closure() -> None:
    infos = {"arm_takeoff": RungInfo("sim-flown"),
             "rover_follow": RungInfo("simulated"),
             "challenge_2": RungInfo("simulated")}
    text, complete = format_plan(_reg(), infos, "challenge_2")
    assert not complete and "rover_follow" in text and "arm_takeoff" not in text
```

- [ ] **Step 2: Implement**

```python
#!/usr/bin/env python3
"""tools/cap_plan.py -- the agent's build-order over the claims DAG.

Prints one literal runnable command per claim below sim-flown, dependencies
first. The background agent's loop: run `just cap plan`, execute the top
actionable line, `just cap record`, repeat until LADDER COMPLETE (exit 0).
"""
from __future__ import annotations

from cap_status import RungInfo


def topo_order(data: dict) -> list[str]:
    caps = data.get("capabilities", {})
    seen: list[str] = []

    def visit(name: str) -> None:
        if name in seen or name not in caps:
            return
        for dep in caps[name].get("requires", []):
            visit(dep)
        seen.append(name)

    for name in caps:
        visit(name)
    return seen


def next_action(name: str, entry: dict, info: RungInfo) -> str:
    if "scenario_file" not in entry:
        return "(composite: prove requires below)"
    stem = entry["scenario_file"].removesuffix(".py")
    if "scenario missing" in info.reason:
        return f"just scenario-new {stem}"
    if "mission sim failing" in info.reason or "mission missing" in info.reason:
        return f"just mission sim {entry.get('mission', '')}".strip()
    if info.rung == "declared":
        return f"fix artifacts: {info.reason}"
    return f"just scenario {stem}"


def _closure(data: dict, target: str) -> set[str]:
    caps = data.get("capabilities", {})
    out: set[str] = set()

    def visit(name: str) -> None:
        if name in out or name not in caps:
            return
        out.add(name)
        for dep in caps[name].get("requires", []):
            visit(dep)

    visit(target)
    return out


def format_plan(data: dict, infos: dict[str, RungInfo],
                target: str | None) -> tuple[str, bool]:
    from cap_status import display

    caps = data.get("capabilities", {})
    scope = _closure(data, target) if target else set(caps)
    lines: list[str] = []
    for name in topo_order(data):
        if name not in scope:
            continue
        info = infos[name]
        if info.rung == "sim-flown":
            continue
        lines.append(f"{name:<22} {display(info):<34} {next_action(name, caps[name], info)}")
    if not lines:
        where = f" for {target}" if target else ""
        return (f"LADDER COMPLETE{where}: everything sim-flown and fresh", True)
    return ("\n".join(lines), False)
```

And in `tools/capabilities.py`:

```python
@app.command()
def plan(claim: str = typer.Argument("", help="Scope to this claim's requires closure")) -> None:
    """Frontier: what to do next, dependencies first. Exit 0 = ladder complete."""
    from cap_evidence import EVIDENCE_ROOT, load_records
    from cap_plan import format_plan
    from cap_status import derive_all, real_artifacts_ok, real_changed_since, real_mission_ok

    data = _load()
    caps = data.get("capabilities", {})
    if claim and claim not in caps:
        typer.echo(f"NO SUCH CLAIM: {claim}", err=True)
        raise typer.Exit(2)
    records = {name: load_records(EVIDENCE_ROOT, name) for name in caps}
    infos = derive_all(data, records, real_changed_since, real_artifacts_ok, real_mission_ok)
    text, complete = format_plan(data, infos, claim or None)
    typer.echo(text)
    raise typer.Exit(0 if complete else 1)
```

- [ ] **Step 3: Verify + commit**

Run: `uv run pytest tests/unit/test_cap_plan.py -q` -> pass.
Smoke: `just cap plan` -> 8 lines, each `just scenario <stem>` (no evidence
yet), exit 1. `just cap plan ghost` -> exit 2.
`git commit -am "feat(cap): cap plan frontier over the requires DAG"`

### Task 7: Agent contract docs (`docs/CLAIMS.md`, AGENTS.md)

**Files:**
- Create: `docs/CLAIMS.md`
- Modify: `AGENTS.md` (Tooling row, workflows row, Verify row, Code-changes
  bullet, new short "Claims" section), `README.md` if it names cap commands

- [ ] **Step 1: Write `docs/CLAIMS.md`** covering, in the README's terse
  table style (no em dashes, no Unicode arrows): the claim TOML fields
  (each field, type, required-for-leaf/composite); the rung table with
  exact derivation criteria (copy from the spec's section 3); evidence
  record schema with the JSON example; the three commands with exit codes;
  the two workflows (add a claim = edit `tests/capabilities.toml` then
  `just check`; advance = run what `cap plan` prints, then
  `just cap record <claim>`, then commit the evidence file); staleness
  semantics and the flight-relevant path list; extension slots (hw-flown:
  `platform = "hw"`; sim-golden: the reserved `grade` field, skein delta).
- [ ] **Step 2: AGENTS.md** -- add a "Claims" section (~15 lines): rung
  ladder one-liner, the three commands in the Tooling/workflow tables, and
  a pointer to docs/CLAIMS.md. Update the "Code changes" scenario bullet:
  registry entry snippet now shows `requires`, no `status`; replace
  "run `just cap mark <id> sim` after a PASS" with "run
  `just cap record <id>` after a PASS and commit the evidence file".
- [ ] **Step 3: Verify + commit**

Run: `just check` -> exit 0 (check_docs validates the new identifiers).
Run: `rg -n "cap mark|last_verified|\"unverified\"" AGENTS.md README.md docs/ tools/ tasks.py`
-> no live references (plans/ and this file excepted).
`git commit -am "docs: claims ladder contract (CLAIMS.md + AGENTS.md)"`

### Task 8: Full gate

- [ ] `just check` -> exit 0 (validator, all new tests, docs net).
- [ ] `just cap show` -> 8 leaves at `simulated`, `0/8 sim-flown` (no
  evidence yet -- seeding happens in plan 075's live gate).
- [ ] `just cap plan` -> 8 fly actions, exit 1.
- [ ] Update this plan's row in `plans/README.md`.

## Test plan

Tasks 1, 3, 4, 5, 6 are TDD with the test code given inline. CLI smoke
checks cover exit codes 2/3. The live seeding gate (e2e -> evidence for all
8 claims -> `cap plan` LADDER COMPLETE) belongs to plan 075, which adds e2e
auto-record.

## Done criteria

- [ ] `just check` gates the registry (introduce a fake cycle locally ->
      check fails naming it; revert)
- [ ] `rg -n "cap mark" .` -> matches only in plans/ history
- [ ] `just cap show` / `plan` / `record` behave per Tasks 4-6 smoke checks
- [ ] `tests/evidence/.gitkeep` committed; ledger writes there
- [ ] docs/CLAIMS.md exists; AGENTS.md Claims section present; check_docs green
- [ ] `plans/README.md` row updated

## STOP conditions

- `scenario_sim_configs` or `scenarios_for_platform` need behavior changes
  (they are plan 075's seam -- do not touch here).
- Anything requires `src/` to read `tests/capabilities.toml` (layering).
- `mission_cli.py` has no usable dry-run subcommand (check `--help` first;
  report instead of inventing one).
- check_docs rejects a doc identifier you cannot resolve -- report, do not
  allowlist.

## Maintenance notes

- The rung vocabulary and `RUNG_ORDER` are load-bearing for plan 075 and
  docs/CLAIMS.md; extend only by appending (hw-flown slots after sim-flown).
- Evidence schema changes require a migration note in docs/CLAIMS.md; the
  `grade`/`conditions`/`platform` fields are reserved slots (spec section
  "What is deliberately NOT built").
