# Plan 075: Claims integration — mission `requires`, e2e DAG ordering + prerequisite skipping, auto-recorded evidence

> **For agentic workers:** execute task-by-task with the checkbox steps; run
> every Verify before the next step. Spec:
> `docs/superpowers/specs/2026-07-17-claims-ladder-design.md`. If anything in
> "STOP conditions" occurs, stop and report. Update this plan's row in
> `plans/README.md` when done.
>
> **Drift check (run first)**:
> `git diff --stat <074-merge>..HEAD -- tools/capabilities.py tools/cap_evidence.py tools/cap_status.py tasks.py src/core/ros_px4_template_core/lib/mission tools/mission_cli.py tests/unit/`
> (`<074-merge>` = the commit where plan 074 landed.) On any mismatch with
> the "Current state" excerpts below, STOP.

**Goal:** wire the claims ladder into the two live surfaces: missions
declare `requires` (shape-checked in lib, registry-checked in
`mission validate`), and `just test e2e` runs in DAG order, skips dependents
of failed claims with a named reason, filters out below-`simulated` claims,
and auto-records evidence on PASS — closing the loop so one e2e run seeds
the whole ledger.

**Architecture:** lib gains only a shape-validated passthrough field (src/
stays registry-blind); all registry-aware logic lives in tools/ and
tasks.py. e2e roster/order/skip logic is pure functions in
`tools/capabilities.py` + a small tasks.py rewire, reusing plan 070's
`_fallback_scenario_report` for skip reports.

**Tech stack:** as plan 074. All live commands run inside distrobox.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MED (touches the e2e scheduler; the live gate is the real proof)
- **Depends on**: 074 (HARD: ledger, rungs, registry schema), 070 (HARD:
  `_fallback_scenario_report`), 069 (soft: same loader region, land first
  to avoid merge noise)
- **Category**: direction / feature
- **Planned at**: commit `5c1124f`, 2026-07-17

## Global constraints

- Same as plan 074 (house style; layering: `src/` never reads
  `tests/capabilities.toml`; verdict + exit-code contract).
- A dirty tree must never fail a flight run: auto-record SKIPS with an
  instruction, never errors.
- Skipped scenarios COUNT AS FAILS (they did not pass) and never record
  evidence.

## Current state

- Post-074: `tools/capabilities.py` has `show`/`record`/`plan` +
  `scenario_sim_configs` (unchanged contract:
  `{"scenario","vision","overlay","model","world"}` in TOML order);
  `tools/cap_evidence.py` (`build_record`, `write_record`,
  `dirty_flight_paths`, `EVIDENCE_ROOT`); `tools/cap_status.py`
  (`derive_all`, `real_artifacts_ok`, ...); registry has `requires`.
- Post-070: `tasks.py` has `_fallback_scenario_report(scenario, reason,
  config) -> str` and the per-scenario freshness check in
  `_run_e2e_sim_group`'s loop (was lines 1008-1014 at `6ce9aec`).
- `tasks.py` e2e flow: `test("e2e")` -> `_e2e_run(configs)` iterates groups
  from `_e2e_sim_groups(configs)`; configs come from
  `scenario_sim_configs("sim")` (`tasks.py:199`); empty roster fails
  (`tasks.py:1119`). `_e2e_sim_groups` is pinned by
  `tests/unit/test_tasks_e2e_groups.py`.
- Mission YAML: parsed by `lib/mission/loader.py` (`load_mission_dict`);
  unknown top-level keys — check current behavior: read the loader before
  editing (plan 069 may have added strictness). `tools/mission_cli.py` has
  `validate`/`show`/`sim` commands wrapping the loader (exit 2 on
  MissionError).
- Scenario-to-claim mapping: each registry leaf has `scenario_file`; the
  stem (`01_arm_takeoff`) is the scenario name used by e2e configs.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Quality gate | `just check` | exit 0 |
| Group tests | `uv run pytest tests/unit/test_tasks_e2e_groups.py tests/unit/test_capabilities.py -q` | all pass |
| Mission checks | `uv run python tools/mission_cli.py validate <name>` | exit 0 |
| Live gate | `just test e2e` | 8/8 PASS + evidence recorded |
| Ladder check | `just cap plan` | LADDER COMPLETE, exit 0 |

## Scope

**In scope**: `src/core/ros_px4_template_core/lib/mission/loader.py` (+ its
types if `requires` is stored on `Mission`), `tools/mission_cli.py`,
`tools/capabilities.py` (roster/order/skip pure functions), `tasks.py` (e2e
wiring), `tests/unit/` (loader, mission_cli, roster/order/skip tests),
`config/missions/*.yaml` (add `requires` to the shipped missions),
`docs/MISSIONS.md` (one `requires` row in the YAML-schema section),
`docs/CLAIMS.md` (mission + e2e paragraphs), `tests/evidence/` (seeded by
the live gate).

**Out of scope**: engine/behaviors/guards; scenario scripts; `cap
show/record/plan` internals (074); skein.

## Git workflow

- Branch: `advisor/075-claims-integration`
- Commit per task. Do NOT push unless told.

---

### Task 1: Mission `requires` — shape in lib, registry check in `mission validate`

**Files:**
- Modify: `src/core/ros_px4_template_core/lib/mission/loader.py`,
  `src/core/ros_px4_template_core/lib/mission/types.py` (`Mission` gains
  `requires: tuple[str, ...] = ()`)
- Modify: `tools/mission_cli.py` (validate cross-check)
- Modify: `config/missions/*.yaml` (see table below)
- Test: `tests/unit/test_mission_loader.py`, `tests/unit/test_mission_cli.py`
- Docs: `docs/MISSIONS.md` YAML-schema section (one row); regenerate the
  schema ONLY if the generator includes top-level keys (check
  `tools/mission_cli.py schema` / `build_schema` first — if `requires`
  changes `schemas/mission.schema.json`, commit the regen; the drift test
  will tell you).

**Interfaces:**
- Produces: `Mission.requires: tuple[str, ...]`; `mission validate` exit 2
  on unknown claim id, WARNING line
  `WARN: required claim '<id>' is below sim-flown (<rung>)` otherwise.
- Consumes: 074's `derive_all` + real_* helpers for the rung lookup.

- [ ] **Step 1: Failing loader tests** (add to `tests/unit/test_mission_loader.py`,
  matching its existing style — read the file first):

```python
def test_requires_parsed_as_tuple() -> None:
    doc = _minimal_mission_doc()          # use the file's existing fixture helper
    doc["requires"] = ["arm_takeoff", "aruco_hover"]
    m = load_mission_dict(doc, base_dir=Path("."))
    assert m.requires == ("arm_takeoff", "aruco_hover")

def test_requires_defaults_empty() -> None:
    m = load_mission_dict(_minimal_mission_doc(), base_dir=Path("."))
    assert m.requires == ()

def test_requires_wrong_shape_raises() -> None:
    doc = _minimal_mission_doc()
    doc["requires"] = "arm_takeoff"
    with pytest.raises(MissionError, match="requires"):
        load_mission_dict(doc, base_dir=Path("."))
```

(If `test_mission_loader.py` has no minimal-doc helper, build the doc dict
inline copying the smallest existing loader test.)

- [ ] **Step 2: Implement** — in `types.py` add the field to the frozen
  `Mission` dataclass (`requires: tuple[str, ...] = ()`); in `loader.py`,
  where the top-level document keys are read, add:

```python
requires_raw = doc.get("requires", [])
if not (isinstance(requires_raw, list) and all(isinstance(r, str) for r in requires_raw)):
    raise MissionError("'requires' must be a list of claim-id strings")
```

and pass `requires=tuple(requires_raw)` into the `Mission(...)`
construction. The loader validates SHAPE ONLY — it must not read the
registry (layering).

- [ ] **Step 3: `mission validate` cross-check** in `tools/mission_cli.py`,
  inside the existing validate command after a successful load:

```python
from capabilities import _load as _load_registry
from cap_evidence import EVIDENCE_ROOT, load_records
from cap_status import derive_all, display, real_artifacts_ok, real_changed_since, real_mission_ok

data = _load_registry()
caps = data.get("capabilities", {})
unknown = [r for r in mission.requires if r not in caps]
if unknown:
    print(f"UNKNOWN CLAIM(S) in requires: {', '.join(unknown)} (see tests/capabilities.toml)",
          file=sys.stderr)
    raise SystemExit(2)
if mission.requires:
    records = {n: load_records(EVIDENCE_ROOT, n) for n in caps}
    infos = derive_all(data, records, real_changed_since, real_artifacts_ok, real_mission_ok)
    for r in mission.requires:
        if infos[r].rung != "sim-flown":
            print(f"WARN: required claim '{r}' is below sim-flown ({display(infos[r])})")
```

CAUTION: `real_mission_ok` shells back into `mission_cli sim` — for the
mission being validated this is fine (different subcommand), but pass a
cheap stub instead if you see recursion in practice: only claims WITH a
`mission` field trigger it, so validate a mission that is itself required
by a claim carefully (arm_takeoff etc. have no `mission` field today; if a
future registry entry points `mission` at the mission being validated,
guard with a max-depth env var and report). Add a unit test with a fake
registry file for the unknown-id exit 2 path (mission_cli tests already
fake paths — follow `tests/unit/test_mission_cli.py` style).

- [ ] **Step 4: Ship `requires` in the shipped missions**

| mission | requires |
|---------|----------|
| `demo.yaml` | `["waypoint_nav"]` |
| `hover.yaml` | `["hover_hold"]` |
| `marker_hover.yaml` | `["aruco_hover"]` |
| `precision_land.yaml` | `["precision_land"]` |
| `search_relocalize.yaml` | `["search_relocalize"]` |
| `yaw_demo.yaml` | `["yaw_control"]` |

- [ ] **Step 5: Verify + commit**

Run: `uv run pytest tests/unit/test_mission_loader.py tests/unit/test_mission_cli.py tests/unit/test_mission_schema.py -q` -> pass
(regen schema if the drift test demands it).
Run: `uv run python tools/mission_cli.py validate demo` -> exit 0 (a WARN
line is fine pre-seeding). `just check` -> exit 0.
`git commit -am "feat(mission): requires field (shape in lib, registry check in validate)"`

### Task 2: e2e roster filter + DAG ordering (pure)

**Files:**
- Modify: `tools/capabilities.py`
- Test: `tests/unit/test_capabilities.py`

**Interfaces:**
- Produces:
  - `claim_for_scenario(data: dict, scenario: str) -> str | None`
  - `e2e_roster(data: dict, artifacts_ok: Callable[[dict], tuple[bool, str]], platform: str = "sim") -> tuple[list[dict], list[str]]`
    — (configs in TOPO order, excluded claim names below `simulated`).
    Config dict shape is IDENTICAL to `scenario_sim_configs` output.
- Consumes: `topo_order` from `tools/cap_plan.py`; existing
  `scenario_sim_configs`.

- [ ] **Step 1: Failing tests** (add to `tests/unit/test_capabilities.py`):

```python
def test_e2e_roster_topo_orders_and_excludes_unscaffolded(tmp_path: Path) -> None:
    from capabilities import e2e_roster
    reg = tmp_path / "capabilities.toml"
    _write_registry(reg, {
        # registry order deliberately NOT topo order
        "precision_land": {"description": "d", "platforms": ["sim"],
                           "scenario_file": "08_precision_land.py",
                           "requires": ["aruco_hover"]},
        "aruco_hover": {"description": "d", "platforms": ["sim"],
                        "scenario_file": "05_aruco_hover.py", "requires": []},
        "rover_follow": {"description": "d", "platforms": ["sim"],
                         "scenario_file": "10_rover_follow.py",
                         "requires": ["aruco_hover"]},
        "challenge": {"description": "d", "requires": ["rover_follow"]},
    })
    def artifacts_ok(entry: dict) -> tuple[bool, str]:
        ok = entry.get("scenario_file") != "10_rover_follow.py"
        return ok, "" if ok else "scenario missing"
    configs, excluded = e2e_roster(_load_from_path(reg), artifacts_ok)
    assert [c["scenario"] for c in configs] == ["05_aruco_hover", "08_precision_land"]
    assert excluded == ["rover_follow"]

def test_claim_for_scenario_maps_stem() -> None:
    from capabilities import claim_for_scenario
    data = {"capabilities": {"aruco_hover": {"scenario_file": "05_aruco_hover.py"}}}
    assert claim_for_scenario(data, "05_aruco_hover") == "aruco_hover"
    assert claim_for_scenario(data, "zz_missing") is None
```

(Add a `_load_from_path` helper mirroring the file's `_load_from` if
needed.)

- [ ] **Step 2: Implement** in `tools/capabilities.py`:

```python
def claim_for_scenario(data: dict, scenario: str) -> str | None:
    for name, entry in data.get("capabilities", {}).items():
        if entry.get("scenario_file", "").removesuffix(".py") == scenario:
            return name
    return None


def e2e_roster(data: dict, artifacts_ok, platform: str = "sim") -> tuple[list[dict], list[str]]:
    """Topo-ordered e2e configs; leaves below `simulated` are excluded (named).

    Same config shape as scenario_sim_configs; composites never enter the
    roster (nothing to fly)."""
    from cap_plan import topo_order

    caps = data.get("capabilities", {})
    configs: list[dict] = []
    excluded: list[str] = []
    for name in topo_order(data):
        entry = caps[name]
        if platform not in entry.get("platforms", []) or not entry.get("scenario_file"):
            continue
        ok, _why = artifacts_ok(entry)
        if not ok:
            excluded.append(name)
            continue
        configs.append({
            "scenario": entry["scenario_file"].removesuffix(".py"),
            "vision": entry.get("sim_vision", "none"),
            "overlay": entry.get("sim_overlay", "auto_arm"),
            "model": entry.get("sim_model", "x500"),
            "world": entry.get("sim_world", "default"),
        })
    return configs, excluded
```

- [ ] **Step 3: Verify + commit**

Run: `uv run pytest tests/unit/test_capabilities.py -q` -> pass.
`git commit -am "feat(cap): topo-ordered e2e roster with declared-claim exclusion"`

### Task 3: e2e uses the roster; prerequisite skipping; auto-record

**Files:**
- Modify: `tasks.py` (e2e config sourcing; `_run_e2e_sim_group` scenario
  loop; a pure helper)
- Test: `tests/unit/test_tasks_e2e_groups.py`

**Interfaces:**
- Produces: `_blocked_by(data: dict, scenario: str, failed_claims: set[str]) -> str | None`
  (pure, in tasks.py: the transitively-required failed claim blocking this
  scenario, else None). e2e behavior: topo roster; excluded claims printed;
  scenario skipped when `_blocked_by` hits -> synthesized report
  `reason: "prerequisite_failed:<claim>"`, counted as fail, no evidence;
  PASS -> auto-record unless dirty tree (skip note).
- Consumes: `e2e_roster`/`claim_for_scenario` (Task 2), 070's
  `_fallback_scenario_report`, 074's `build_record`/`write_record`/
  `dirty_flight_paths`.

- [ ] **Step 1: Failing tests** (extend `tests/unit/test_tasks_e2e_groups.py`,
  which already imports from `tasks`):

```python
def test_blocked_by_transitive_failed_claim() -> None:
    from tasks import _blocked_by
    data = {"capabilities": {
        "arm_takeoff": {"scenario_file": "01_arm_takeoff.py", "requires": []},
        "aruco_hover": {"scenario_file": "05_aruco_hover.py", "requires": ["arm_takeoff"]},
        "precision_land": {"scenario_file": "08_precision_land.py", "requires": ["aruco_hover"]},
    }}
    assert _blocked_by(data, "08_precision_land", {"arm_takeoff"}) == "arm_takeoff"
    assert _blocked_by(data, "08_precision_land", set()) is None
    assert _blocked_by(data, "01_arm_takeoff", {"aruco_hover"}) is None
```

- [ ] **Step 2: Implement `_blocked_by`** in tasks.py (near the e2e code):

```python
def _blocked_by(data: dict, scenario: str, failed_claims: set[str]) -> str | None:
    """First transitively-required claim of `scenario` that already failed."""
    from capabilities import claim_for_scenario

    caps = data.get("capabilities", {})
    name = claim_for_scenario(data, scenario)
    if name is None:
        return None
    seen: set[str] = set()
    stack = list(caps.get(name, {}).get("requires", []))
    while stack:
        dep = stack.pop()
        if dep in seen:
            continue
        seen.add(dep)
        if dep in failed_claims:
            return dep
        stack.extend(caps.get(dep, {}).get("requires", []))
    return None
```

- [ ] **Step 3: Rewire e2e**

1. Where `test("e2e")` builds `configs = scenario_sim_configs("sim")`,
   switch to:

```python
from capabilities import _load as _load_registry, e2e_roster
from cap_status import real_artifacts_ok

registry = _load_registry()
configs, excluded = e2e_roster(registry, real_artifacts_ok)
for name in excluded:
    print(f"  [NOTE] claim '{name}' is below simulated (not scaffolded) — excluded from e2e")
```

   (Keep the empty-roster failure at `tasks.py:1119` working on the new
   `configs`.) Thread `registry` and a shared `failed_claims: set[str]`
   through to `_run_e2e_sim_group` (new parameters with defaults so the
   signature stays compatible with existing tests).
2. In `_run_e2e_sim_group`'s scenario loop (post-070 shape), BEFORE
   launching a scenario subprocess:

```python
blocker = _blocked_by(registry, s, failed_claims)
if blocker is not None:
    fails += 1
    print(f"  [SKIP] {s}: prerequisite claim '{blocker}' failed this run", file=sys.stderr)
    (LOG_DIR / f"scenario_{s}.json").write_text(
        _fallback_scenario_report(
            s, f"prerequisite_failed:{blocker}",
            {"vision": vision, "overlay": overlay, "model": model, "world": world},
        ), encoding="utf-8")
    continue
```

3. On scenario FAIL (nonzero exit or no fresh report), add its claim:
   `failed_claims.add(claim_for_scenario(registry, s) or s)`.
4. On PASS (exit 0 + fresh report), auto-record:

```python
from cap_evidence import EVIDENCE_ROOT, build_record, dirty_flight_paths, write_record

entry = registry["capabilities"].get(claim_for_scenario(registry, s) or "", {})
porcelain = subprocess.run(["git", "status", "--porcelain"],
                           capture_output=True, text=True, cwd=str(ROOT)).stdout
dirty = dirty_flight_paths(porcelain, entry.get("scenario_file"))
if dirty:
    print(f"  [NOTE] evidence not recorded for {s} (dirty tree): commit, then just cap record "
          f"{claim_for_scenario(registry, s)}")
else:
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                            capture_output=True, text=True, cwd=str(ROOT)).stdout.strip()
    report = json.loads((LOG_DIR / f"scenario_{s}.json").read_text(encoding="utf-8"))
    rec = build_record(claim_for_scenario(registry, s), "sim", commit, report,
                       {"world": world, "model": model, "vision": vision})
    write_record(rec, EVIDENCE_ROOT)
    print(f"  [EVIDENCE] {s} PASS recorded @ {commit}")
```

(Extract this block into a small `_auto_record(...)` function in tasks.py
so the loop stays readable; skip recording entirely when
`claim_for_scenario` returns None.)

- [ ] **Step 4: Verify + commit**

Run: `uv run pytest tests/unit/test_tasks_e2e_groups.py -q` -> pass
(update the existing grouping test only if you changed `_e2e_sim_groups`'s
inputs — the roster reorders configs BEFORE grouping, so `_e2e_sim_groups`
itself stays untouched).
Run: `just check` -> exit 0.
`git commit -am "feat(e2e): DAG order, prerequisite skipping, auto-recorded evidence"`

### Task 4: Docs + live gate (operator)

- [ ] **Step 1: Docs.** `docs/CLAIMS.md`: add the mission-`requires` and
  e2e paragraphs (ordering, `prerequisite_failed:<claim>` reason,
  auto-record + dirty-tree note). `docs/MISSIONS.md`: `requires` row in the
  YAML schema section. AGENTS.md e2e bullet: one sentence on DAG order +
  evidence auto-record.
- [ ] **Step 2: Live gate** (sim-capable operator, inside distrobox):
  `just check` clean tree, then `just test e2e` -> 8/8 PASS, `[EVIDENCE]`
  line per scenario. Then:
  - `just cap show` -> `8/8 sim-flown`
  - `just cap plan` -> `LADDER COMPLETE`, exit 0
  - `git status` -> 8 new files under `tests/evidence/`; commit them:
    `git add tests/evidence && git commit -m "test(evidence): seed claims ledger from live e2e"`
  - Negative probe (staleness decay): edit a comment in any `src/` file,
    commit it, run `just cap show` -> every leaf shows
    `sim-flown (stale, since ...)`. Then `git revert --no-edit HEAD` and
    `just cap show` -> fresh again: the revert is a new commit but
    `git diff --name-only <evidence-commit>..HEAD` compares TREES, which
    now match — proving staleness is content-based, not commit-count-based.
- [ ] **Step 3:** update this plan's row in `plans/README.md`.

## Test plan

Tasks 1-3 are TDD (test code inline). The live gate (Task 4) is the
integration proof: one e2e run seeds the ledger, the ladder reports
complete, and the staleness probe demonstrates automatic decay.

## Done criteria

- [ ] `Mission.requires` parsed (shape-only in lib); `mission validate`
      exit 2 on unknown id, WARN below sim-flown
- [ ] e2e prints excluded declared claims; runs in topo order
- [ ] A failed claim's dependents are skipped with
      `prerequisite_failed:<claim>` reports, counted as fails
- [ ] PASS auto-records evidence; dirty tree prints the commit-first note
- [ ] Live: 8/8 PASS -> `cap plan` LADDER COMPLETE -> evidence committed
- [ ] Staleness probe: a src/ commit flips all leaves to stale; revert
      restores fresh
- [ ] `just check` -> exit 0; `plans/README.md` row updated

## STOP conditions

- 070 or 074 not merged (hard dependencies).
- The loader region conflicts with un-merged 069 work — land 069 first.
- `mission validate`'s rung lookup recurses (see Task 1 caution) — stub and
  report rather than shipping a hang.
- The live e2e fails a scenario that passed before this branch — your
  ordering change altered a boot config; diff the printed group banners
  against a pre-branch run and report.

## Maintenance notes

- `e2e_roster` is now the single source of the e2e schedule;
  `scenario_sim_configs` remains for `just scenario <name>` single-boot
  resolution. If the shapes ever diverge, unify — divergence is a bug.
- Skip reasons (`prerequisite_failed:<claim>`) join the agent-facing
  vocabulary next to `sim_never_ready` / `crashed_before_report` (plan
  070); keep them stable.
