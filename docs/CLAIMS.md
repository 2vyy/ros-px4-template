# Claims ladder

A claim is a statement about what the system can do ("vehicle centers on the marker, descends, and lands"). `tests/capabilities.toml` is the authoring API: it stores claim structure and artifact pointers, nothing else. **Rungs are derived** from the registry, artifacts, Git history, and committed PASS evidence - never stored, so they cannot lie. Nothing under `src/` reads the registry.

## Claim registry

Each `[capabilities.<id>]` table is either a leaf with `scenario_file` or a composite without it.

| Field | Type | Leaf | Composite | Meaning |
|-------|------|------|-----------|---------|
| `description` | string | Required | Required | Non-empty human claim. |
| `requires` | list of claim ids | Optional, defaults to empty | Required, non-empty | Dependency DAG edges. Unknown ids and cycles are invalid. |
| `scenario_file` | string | Required | Forbidden | File under `tests/scenarios/` that proves the leaf. |
| `platforms` | list of `sim` or `hw` | Required, non-empty | Optional | Platforms on which the leaf can run. |
| `params` | table | Optional | Optional | Quantities and tolerances from the claim source. |
| `source` | string | Optional | Optional | Provenance, usually a rules-document section. |
| `mission` | string | Optional | Optional | Mission name under `config/missions/`, without `.yaml`. |
| `sim_vision` | string | Optional | Optional | Sim vision mode. Current values: `none`, `aruco`. Default: `none`. |
| `sim_overlay` | string | Optional | Optional | Parameter overlay name under `config/params/overlays/`. Default: `auto_arm`. |
| `sim_world` | string | Optional | Optional | World name under `sim/worlds/`. Default: `default`. |
| `sim_model` | string | Optional | Optional | Model under `sim/models/`, or PX4-shipped `x500`. Default: `x500`. |

`just check` rejects malformed fields, unknown dependencies, cycles, empty composites, and unknown platforms. Missing artifacts do not invalidate a claim: they keep it at `declared`, so a claim can be registered before implementation.

Example leaf:

```toml
[capabilities.precision_land]
description = "Vehicle centers on the marker, descends, and lands"
requires = ["aruco_hover"]
params = { xy_tol_m = 0.3 }
source = "competition rules, landing task"
scenario_file = "08_precision_land.py"
mission = "precision_land"
platforms = ["sim"]
sim_vision = "aruco"
sim_overlay = "precision_land"
sim_world = "default"
sim_model = "x500"
```

A composite omits `scenario_file` and has a non-empty `requires`. Its rung is the minimum rung of its dependency closure.

## Derived rungs

Load-bearing order:

```text
declared < simulated < sim-flown-stale < sim-flown
```

| Rung | Exact derivation criteria |
|------|---------------------------|
| `declared` | The entry exists and passes registry validation, but no higher rung is proven. |
| `simulated` | The scenario, overlay, world, model, vision mode, and optional mission file resolve. If `mission` is set, `just mission sim <name> --require-terminal` must reach terminal. |
| `sim-flown-stale` | Committed sim PASS evidence exists, but its commit is unknown or its diff to HEAD intersects a flight-relevant path. Displayed as `sim-flown (stale, since <commit>)`. |
| `sim-flown` | The newest committed, unchanged sim PASS evidence has a known commit and no flight-relevant diff from that commit to HEAD. |

`just cap show` prints claim, derived rung, evidence age, and the reason for a lower or stale rung. Unreadable, uncommitted, or modified evidence JSON is ignored with a warning that names the file.

Flight-relevant paths are defined once in `tools/cap_evidence.py`:

- `src/`
- `sim/`
- `config/`
- the claim's own `tests/scenarios/<scenario_file>`
- the claim's own entry in `tests/capabilities.toml`

Documentation, plans, and another claim's scenario or registry entry do not stale the claim. An evidence commit removed by rebase or history rewrite produces `commit_unknown` and a stale rung.

## Evidence ledger

PASS evidence is committed under `tests/evidence/<claim>/`. The filename is `<run_id>_<platform>.json`. Recording keeps the newest three files per claim x platform. FAIL reports stay in `logs/`.

```json
{
  "claim": "precision_land",
  "platform": "sim",
  "commit": "5c1124f",
  "run_id": "20260717_141530",
  "verdict": "PASS",
  "elapsed_s": 141.2,
  "detail": {
    "xy_err": 0.06,
    "froze_on_loss": true
  },
  "conditions": {
    "world": "default",
    "model": "x500",
    "vision": "aruco"
  },
  "grade": null
}
```

| Field | Meaning |
|-------|---------|
| `claim` | Registry claim id. |
| `platform` | Platform that produced the run. Current recorder writes `sim`. |
| `commit` | Short Git revision whose flight-relevant tree produced the run. |
| `run_id` | UTC run timestamp in `YYYYMMDD_HHMMSS` form. |
| `verdict` | Always `PASS`. |
| `elapsed_s` | Scenario elapsed seconds. |
| `detail` | Scenario report detail dict, verbatim. |
| `conditions` | World, model, and vision facts for the run. |
| `grade` | Reserved for future golden-run grading. Currently `null`. |

`just cap record <claim>` reads `logs/scenario_<name>.json`, requires PASS, requires the report mtime to be at or after HEAD, and refuses a dirty flight-relevant tree. This ensures the evidence commit reproduces the flown code. Commit the new evidence file deliberately.

## Commands and exits

| Command | Result | Exit codes |
|---------|--------|------------|
| `just cap show` | Derived table for every claim. | `0` shown. |
| `just cap plan [claim]` | Dependency-first incomplete frontier, optionally scoped to one closure. | `0` ladder complete, `1` actions remain, `2` unknown claim. |
| `just cap record <claim>` | Record and prune fresh sim PASS evidence. | `0` recorded, `2` unknown or composite claim, `3` missing, failed, stale report, dirty tree, or Git precondition. |

`cap plan` prints one next action per incomplete claim. Run the first actionable command. A missing scenario prints `just scenario-new <name>`, a failing mission prints `just mission sim <name> --require-terminal`, and a simulated or stale leaf prints `just run <name>`. `LADDER COMPLETE` means the selected closure is fresh at `sim-flown`.

## Workflows

### Add a claim

1. Edit `tests/capabilities.toml`: `requires`, artifact pointers, optional provenance and parameters.
2. Run `just check`. Fix every named form error. Missing artifacts are expected at `declared`.

### Advance a rung

1. Run `just cap plan` (or `just cap plan <claim>` for one closure).
2. Execute the first actionable command.
3. After a scenario PASS, run `just cap record <claim>` (or let `just e2e` auto-record; see below).
4. Commit the evidence file.
5. Repeat until `LADDER COMPLETE`.

## Mission `requires`

Mission YAML may declare a top-level `requires` list of claim ids. The mission loader validates shape only (list of strings). `just mission validate` cross-checks ids against the registry (exit 2 on unknown) and prints `WARN: required claim '<id>' is below sim-flown (<rung>)` when a required claim is not yet fresh at `sim-flown`. Nothing under `src/` reads the registry.

## E2E integration

`just e2e` builds its roster from `e2e_roster`: claims below `simulated` are excluded with a named `[NOTE]`, and runnable leaves run in `requires` DAG (topo) order. When a claim fails this run, dependents are skipped with synthesized FAIL reports whose reason is `prerequisite_failed:<claim>`; skips count as fails and never record evidence. Each PASS auto-records under `tests/evidence/` and prints `[EVIDENCE]`. If the flight-relevant tree is dirty, auto-record skips with a commit-first `[NOTE]` and the flight still succeeds - never abort a run over an unclean worktree. Commit the new evidence files deliberately after the run.

## Reserved extensions

| Slot | Already shaped | Not built |
|------|----------------|-----------|
| Hardware flight | `platform = "hw"`, shared conditions and detail schema | `hw-flown` derivation and hardware recorder. |
| Golden simulation | `grade`, `conditions` | `sim-golden` rung, run recording, and delta thresholding (the old bag/ULog recording pipeline was removed in plan 085 — resurrect from git history if this rung is ever built). |

Also not built here: claim add/edit commands, FAIL evidence history, and automatic evidence commits (e2e writes evidence files; you still commit them).
