# Plan 067: capabilities.toml and sim CLI are statically validated (config typos fail in `just check`, not after a 30 s boot)

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in "STOP conditions" occurs, stop and report — do not
> improvise. When done, update this plan's row in `plans/README.md` unless a
> reviewer told you they maintain the index.
>
> **Drift check (run first)**:
> `git diff --stat 6ce9aec..HEAD -- tools/capabilities.py tools/check_capabilities.py tasks.py tests/unit/test_check_capabilities.py tests/unit/test_capabilities.py AGENTS.md`
> On any mismatch with the "Current state" excerpts below, STOP.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: LOW
- **Depends on**: none
- **Category**: dx / tests
- **Planned at**: commit `6ce9aec`, 2026-07-16

## Why this matters

`tests/capabilities.toml` is the source of truth that boots every live
scenario and e2e group (`sim_vision`/`sim_overlay`/`sim_model`/`sim_world`),
but nothing validates it: a typo'd world boots a broken sim that fails ~30 s
later as a generic `NOT READY`; `just cap mark <typo> sim` silently CREATES a
blank capability marked "verified" and prints success; `just sim --overlay`
rejects real overlays (`precision_land`, `yaw_demo`) while accepting the
phantom `inspect` (no `inspect.yaml` exists — it dies late inside the launch);
and the `just scenario-new` snippet omits `sim_world`/`sim_model`, so a new
camera challenge silently boots the wrong model. For an agent that must
independently author and verify challenges, each of these costs a full
boot-plus-log-dig round trip for what should be a <1 s static failure. After
this plan, `just check` validates the registry, `cap mark` rejects unknown
ids/platforms with exit 2, `--overlay` validates against the real overlay
files, and the scaffold snippet names all four sim fields.

## Current state

- `tools/capabilities.py` — the registry CLI + accessors:
  - `mark` (lines 37–48): `entry = caps.setdefault(capability, {"description":
    "", "platforms": []})` then sets `status="verified"`,
    `last_verified=date.today().isoformat()`, saves, echoes
    `f"Marked {capability} verified on {platform}"`. No existence check for
    `capability`, no validation of `platform`.
  - `scenario_sim_configs` (lines 61–85): reads each capability's
    `scenario_file` / `sim_vision` / `sim_overlay` / `sim_model` / `sim_world`
    with silent defaults `("none", "auto_arm", "x500", "default")`. Nothing
    checks the values resolve to real files.
- `tasks.py`:
  - `sim()` overlay validation (lines 667–669):
    ```python
    if overlay and overlay not in ("auto_arm", "inspect", "hover"):
        print(f"--overlay must be auto_arm|inspect|hover, got {overlay!r}", file=sys.stderr)
        raise typer.Exit(int(ExitCode.USAGE))
    ```
    Help string at line 655 says `"Param overlay: auto_arm | inspect | hover"`.
    `config/params/overlays/` actually contains: `auto_arm.yaml`, `hover.yaml`,
    `marker_hover.yaml`, `precision_land.yaml`, `search_relocalize.yaml`,
    `yaw_demo.yaml` — no `inspect.yaml`. A missing overlay fails later inside
    `hardware/launch/hardware.launch.py` (~line 50, `RuntimeError: param
    overlay not found`), surfacing only as NOT READY.
  - `check()` (lines 572–645): runs ruff, `tools/check_invariants.py`,
    `tools/check_docs.py` ("Checking agent docs identifiers..."), ty, build,
    pytest; each failure appends to `failed_steps`. New validator wires in
    here, after the check_docs step, same subprocess pattern.
  - `scenario_new` snippet (lines 1266–1273) prints exactly:
    ```python
    print(f"[capabilities.{cap_id}]")
    print('description = "TODO: what this scenario verifies"')
    print('status = "unverified"')
    print('platforms = ["sim"]')
    print(f'scenario_file = "{name}.py"')
    print('sim_vision = "none"')
    print('sim_overlay = "auto_arm"\n')
    ```
- `tests/capabilities.toml` — 9 entries; `aruco_hover_real` may read
  `status = "verified"` by the time you run (a `cap mark` was planned); all
  entries have `platforms = ["sim"]`, a `scenario_file`, and
  `status`/`last_verified` pairs.
- Existing assets to validate against: `sim/worlds/{default,marker_field,landing_pad,obstacle_course}.sdf`;
  `sim/models/{x500_mono_cam_down,aruco_marker_0,aruco_marker_1,aruco_marker_2}/`.
  NOTE: the default model `x500` is PX4's own model, NOT in `sim/models/` —
  the validator must allow it explicitly.
- Test exemplar: `tests/unit/test_scenario_roster.py` (imports
  `from capabilities import ...` — `tests/unit` has `tools/` on its path via
  conftest/pytest config; copy its import style exactly).
- Exit-code convention: `tools/cli_verdict.py` / `ExitCode` in `tasks.py`
  (0 ok, 1 fail, 2 usage, 3 precondition). AGENTS.md documents it.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Quality gate | `just check` | exit 0 (now includes registry check) |
| New tests only | `uv run pytest tests/unit/test_check_capabilities.py -q` | all pass |
| Validator direct | `uv run python tools/check_capabilities.py` | exit 0, `[OK]` lines |
| cap mark misuse | `uv run python tools/capabilities.py mark nope sim` | exit 2, names known ids |

## Scope

**In scope**:
- `tools/check_capabilities.py` (create)
- `tools/capabilities.py` (`mark` validation only)
- `tasks.py` (`check()` wiring; `sim()` overlay validation + help; `scenario_new` snippet)
- `tests/unit/test_check_capabilities.py` (create)
- `AGENTS.md` (the one `--overlay auto_arm|inspect|hover` flags line, and the sim-flags row if it names `inspect`)

**Out of scope** (do NOT touch):
- `tests/capabilities.toml` itself (if the validator finds a REAL
  inconsistency in it, STOP and report — don't silently edit the registry).
- `hardware/launch/hardware.launch.py` — its late failure stays as
  defense-in-depth.
- `tools/scenario_scaffold.py` — the snippet lives in `tasks.py`, not there.
- The e2e runner (`_run_e2e_sim_group`) — it consumes the now-validated
  registry unchanged.

## Git workflow

- Branch: `advisor/067-registry-validation`
- Commit style: `fix(dx): static validation for capabilities.toml, cap mark, and --overlay`
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: `tools/check_capabilities.py`

New tool, modeled on `tools/check_docs.py`'s shape (pure check functions +
a `main()` printing `[OK]`/`[FAIL]` lines, exit 0/1). Pure core:

```python
def check_registry(data: dict, root: Path) -> list[str]:
    """Return a list of human-readable problems; empty = valid."""
```

For every entry in `data["capabilities"]`, check:
1. `scenario_file` set and `root/"tests"/"scenarios"/scenario_file` exists.
2. `platforms` non-empty, every value in `{"sim", "hw"}`.
3. `sim_overlay` (default `"auto_arm"`) →
   `root/"config"/"params"/"overlays"/f"{o}.yaml"` exists.
4. `sim_world` (default `"default"`) → `root/"sim"/"worlds"/f"{w}.sdf"` exists.
5. `sim_model` (default `"x500"`) → `m == "x500"` (PX4-provided stock model)
   OR `root/"sim"/"models"/m` is a directory.
6. `sim_vision` (default `"none"`) in `{"none", "aruco"}`.
7. `status == "verified"` iff `last_verified` parses as an ISO date
   (`date.fromisoformat`) that is not in the future; `status == "unverified"`
   iff `last_verified` is empty/absent. Any other status value is a problem.

Each problem message names the entry, the field, the bad value, and the fix
path, e.g. `capability 'aruco_hover_real': sim_world 'marker_feild' -> sim/worlds/marker_feild.sdf missing`.
`main()` loads the real `tests/capabilities.toml` (reuse
`tools/capabilities.py`'s `_load`) and exits 1 with the problem list, else
prints `[OK] capabilities registry: N entries valid` and exits 0.

**Verify**: `uv run python tools/check_capabilities.py` → exit 0 on the real
registry. (If it exits 1: STOP — the registry has a real problem; report it.)

### Step 2: Wire into `just check`

In `tasks.py` `check()`, after the "Checking agent docs identifiers..." block,
add the same subprocess pattern:

```python
print("Checking capability registry...")
res = subprocess.run(
    ["uv", "run", "python", "tools/check_capabilities.py"], cwd=str(ROOT), env=env
)
if res.returncode != 0:
    failed_steps.append("capability registry")
```

**Verify**: `just check` → exit 0 and the output contains
`Checking capability registry...`.

### Step 3: `cap mark` rejects unknown capability / platform

In `tools/capabilities.py` `mark`: before mutating, if
`capability not in data.get("capabilities", {})`, echo
`unknown capability '<id>'; known: <sorted list>` to stderr and
`raise typer.Exit(2)`. If `platform not in ("sim", "hw")`, echo
`platform must be sim|hw, got '<platform>'` to stderr and `raise
typer.Exit(2)`. Replace the `setdefault` with a plain lookup.

**Verify**:
`uv run python tools/capabilities.py mark nope sim; echo $status` → prints the
known-ids message, exit code 2 (fish; use `echo $?` in bash). And
`uv run python tools/capabilities.py mark arm_takeoff bogus` → exit 2.
(Do NOT run a successful `mark` — it would dirty the registry.)

### Step 4: `--overlay` validates against the filesystem

In `tasks.py` `sim()` replace the tuple check:

```python
if overlay:
    overlay_path = ROOT / "config" / "params" / "overlays" / f"{overlay}.yaml"
    if not overlay_path.is_file():
        available = sorted(p.stem for p in (ROOT / "config" / "params" / "overlays").glob("*.yaml"))
        print(
            f"--overlay '{overlay}' not found ({overlay_path}). Available: {', '.join(available)}",
            file=sys.stderr,
        )
        raise typer.Exit(int(ExitCode.USAGE))
```

Update the option help to `"Param overlay from config/params/overlays/
(default: none, disarmed)."`. Update the `AGENTS.md` sim-flags line: replace
`--overlay auto_arm|inspect|hover` with `--overlay <name>` and, where the
flags are enumerated, note overlays come from `config/params/overlays/`.
Check `rg -n "inspect" AGENTS.md README.md` and remove `inspect` from any
overlay enumerations (do not touch unrelated `inspect_mission.rviz`
references).

**Verify**: `uv run python tasks.py sim --overlay nope --no-build --timeout 1`
→ exit 2 naming the six available overlays (it must fail BEFORE any teardown/
preflight side effects — the validation is first; confirm no
"tearing it down" line printed). Then `just check` → exit 0 (docs check must
still pass after the AGENTS.md edit).

### Step 5: scaffold snippet names all four sim fields

In `tasks.py` `scenario_new`, after the `sim_overlay` print, add:

```python
print('# sim_world = "default"      # a sim/worlds/<name>.sdf; marker worlds need a marker map')
print('# sim_model = "x500"         # set "x500_mono_cam_down" + a marker world for REAL camera detections (docs/SIM.md)\n')
```

(Keep them commented so the defaults stay explicit but inert.)

**Verify**: `uv run python tasks.py scenario-new 99_snippet_check` → output
contains both `sim_world` and `sim_model` lines. Then delete the generated
file: `rm tests/scenarios/99_snippet_check.py`.

### Step 6: Full gate

**Verify**: `just check` → exit 0.

## Test plan

New `tests/unit/test_check_capabilities.py`, modeled on
`tests/unit/test_scenario_roster.py` (same import style for `tools/`):

1. Real-registry test: `check_registry(_load(), ROOT)` returns `[]`.
2. Missing overlay: synthetic registry dict with `sim_overlay="nope"` →
   exactly one problem naming the entry, the field, and the `.yaml` path.
3. Missing world / missing model / stock `x500` allowed (three cases).
4. Status consistency: `verified`+empty date, `unverified`+date,
   `verified`+future date, unknown status → each yields a problem.
5. Bad platform value → problem.
6. `mark` rejection: use `typer.testing.CliRunner` (already used in the test
   suite? verify with `rg CliRunner tests/unit/` — if not present, invoke
   `mark` via subprocess against a COPY of the registry in `tmp_path` by
   monkeypatching `capabilities.REGISTRY`) asserting exit code 2 and the
   known-ids message for an unknown capability.

Verification: `uv run pytest tests/unit/test_check_capabilities.py -q` → all
pass; `just check` → exit 0.

## Done criteria

- [ ] `uv run python tools/check_capabilities.py` exits 0 on the real registry
- [ ] `just check` output includes `Checking capability registry...` and exits 0
- [ ] `uv run python tools/capabilities.py mark nope sim` exits 2 naming known ids
- [ ] `uv run python tasks.py sim --overlay nope --no-build` exits 2 naming available overlays
- [ ] `rg -n '"auto_arm", "inspect", "hover"' tasks.py` → no matches
- [ ] `scenario-new` snippet includes `sim_world` and `sim_model`
- [ ] New unit tests pass; no files outside scope modified (`git status`)
- [ ] `plans/README.md` status row updated

## STOP conditions

- Step 1's validator fails on the REAL registry: the registry itself has a
  latent inconsistency — report it, do not edit `tests/capabilities.toml`.
- `_load()`/registry import from `tests/unit` doesn't resolve the way
  `test_scenario_roster.py` does (path plumbing drifted).
- The AGENTS.md edit trips `tools/check_docs.py` in a way you cannot resolve
  by keeping identifiers backticked and real.

## Maintenance notes

- New capability fields (e.g. a future `sim_speed`) must be added to
  `check_registry` in the same change — reviewers should reject registry-field
  additions that skip the validator.
- Plan 072 (challenge authoring kit) extends this validator with
  world↔marker-map consistency; keep `check_registry` pure and listy so that
  extension is additive.
- The overlay filesystem check intentionally accepts any future overlay file
  without a code change — that is the point.
