# Plan 066: gen_marker_assets.py emits the proven camera-visible marker format

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in "STOP conditions" occurs, stop and report — do not
> improvise. When done, update this plan's row in `plans/README.md` unless a
> reviewer told you they maintain the index.
>
> **Drift check (run first)**:
> `git diff --stat 6ce9aec..HEAD -- tools/gen_marker_assets.py sim/models tests/unit/test_marker_assets.py justfile docs/SIM.md`
> On any mismatch with the "Current state" excerpts below, STOP.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: bug / dx
- **Planned at**: commit `6ce9aec`, 2026-07-16

## Why this matters

Plan 062 proved (live, in sim) that a gz Harmonic camera SENSOR renders a PBR
`albedo_map`-only marker as a solid black square, so `cv2.aruco.detectMarkers`
never resolves it. The committed marker models were hand-fixed to plane
geometry + `emissive_map` + `model://` texture URIs — but the documented
generator, `tools/gen_marker_assets.py`, still emits the OLD format (thin box,
`albedo_map` only, relative texture path). Anyone who reruns the generator
(the documented way to produce marker assets, per `docs/SIM.md`) silently
reverts the fix and breaks all real-pixel perception (`09_aruco_hover_real`,
`--vision aruco` on the camera model) with an opaque "no detections". The
generator also hardcodes ids `(0, 1, 2)` — adding a marker for a new challenge
requires editing generator source. After this plan: the generator's output is
byte-identical to the committed, flight-verified models, a golden test pins
that equivalence forever, and `--ids` + a `just gen-markers` recipe make new
markers a one-command step.

## Current state

- `tools/gen_marker_assets.py` — the generator. `build_model_sdf`
  (lines 100–129) emits:

  ```python
  "        <geometry>\n"
  "          <box>\n"
  f"            <size>{SURFACE_SIZE_M} {SURFACE_SIZE_M} {MODEL_THICKNESS_M}</size>\n"
  ...
  f"              <albedo_map>materials/textures/{texture}</albedo_map>\n"
  ```

  i.e. box geometry, `albedo_map` only, relative texture path. `MARKER_IDS:
  tuple[int, ...] = (0, 1, 2)` at line 32; `main()` (lines 151–159) exposes
  only `--output-root`. Constants: `CODE_SIZE_M = 0.2`, `SURFACE_SIZE_M =
  0.25`, `DICTIONARY_ID = cv2.aruco.DICT_4X4_50`.
- `sim/models/aruco_marker_0/model.sdf` (and `_1`, `_2`) — the committed,
  live-verified format (the ORACLE for this plan):

  ```xml
  <geometry>
    <plane>
      <normal>0 0 1</normal>
      <size>0.25 0.25</size>
    </plane>
  </geometry>
  <material>
    <pbr>
      <metal>
        <!-- emissive_map is load-bearing: in the gz Harmonic camera SENSOR
             render, a PBR albedo_map alone renders the marker as a solid
             black square (no error logged), so cv2.aruco.detectMarkers
             never resolves the pattern. The emissive_map makes the marker
             self-lit and its bit grid readable. Verified plans/062. Use a
             model:// texture URI (relative paths are unreliable in the
             sensor render context). -->
        <albedo_map>model://aruco_marker_0/materials/textures/aruco_marker_0.png</albedo_map>
        <emissive_map>model://aruco_marker_0/materials/textures/aruco_marker_0.png</emissive_map>
        <roughness>1.0</roughness>
        <metalness>0.0</metalness>
      </metal>
    </pbr>
  </material>
  ```

- `tests/unit/test_marker_assets.py` — existing generator tests (from plan
  043); they assert on the OLD output and will need updating.
- `justfile` — no `gen-markers` recipe exists (`rg gen_marker justfile` is
  empty). Recipes delegate to `uv run python tasks.py ...` or tools directly;
  match the existing style in the file.
- Repo conventions: pure render functions, I/O only in `write_model`/`main`
  (keep that split); ruff + ty gate everything via `just check`.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Quality gate | `just check` | exit 0, all unit tests pass |
| Generator tests only | `uv run pytest tests/unit/test_marker_assets.py -q` | all pass |
| Regenerate in place | `uv run python tools/gen_marker_assets.py` | writes 3 model trees |
| Diff check | `git diff --exit-code sim/models/` | exit 0 (no drift) |

## Scope

**In scope** (the only files you may modify):
- `tools/gen_marker_assets.py`
- `tests/unit/test_marker_assets.py`
- `justfile` (add one recipe)
- `sim/models/aruco_marker_{0,1,2}/model.config` (ONLY if step 3 shows the
  generator's config differs from the committed one)

**Out of scope** (do NOT touch):
- `sim/models/aruco_marker_{0,1,2}/model.sdf` and the PNG textures — they are
  the oracle; the generator moves to THEM, never the reverse.
- `sim/models/x500_mono_cam_down/` — the camera model, unrelated.
- `sim/worlds/*.sdf`, `src/`, `docs/SIM.md` prose.

## Git workflow

- Branch: `advisor/066-marker-generator-realignment`
- Commit style: `fix(sim): marker generator emits the proven emissive/plane format`
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Make `build_model_sdf` byte-identical to the committed models

Rewrite `build_model_sdf` so `build_model_sdf(0)` returns EXACTLY the content
of `sim/models/aruco_marker_0/model.sdf` (including the load-bearing comment,
`plane` geometry, both `albedo_map` and `emissive_map` with
`model://{model_name}/materials/textures/{texture}` URIs, and trailing
whitespace/newlines). Read the committed file first and template only the
id-dependent parts (`model name`, the two texture URIs). `MODEL_THICKNESS_M`
becomes unused by the SDF — delete the constant only if nothing else
references it (`rg MODEL_THICKNESS_M`); keep `SURFACE_SIZE_M` (used by the
plane size and `model.config` description).

**Verify**:
`uv run python -c "import sys; sys.path.insert(0,'tools'); from gen_marker_assets import build_model_sdf; from pathlib import Path; sys.exit(0 if build_model_sdf(0)==Path('sim/models/aruco_marker_0/model.sdf').read_text() else 1)"`
→ exit 0.

### Step 2: Golden test pinning generator == committed models

In `tests/unit/test_marker_assets.py`, update any assertions that pin the old
box/albedo output, and add:

```python
def test_generator_matches_committed_models() -> None:
    """The committed models are live-verified (plans/062); the generator must
    reproduce them byte-for-byte so a regeneration can never regress the
    emissive_map fix."""
    for marker_id in (0, 1, 2):
        committed = ROOT / "sim" / "models" / f"aruco_marker_{marker_id}" / "model.sdf"
        assert build_model_sdf(marker_id) == committed.read_text(encoding="utf-8")
```

(Compare `model.config` the same way IF step 3 confirms they match; otherwise
regenerate the three committed `model.config` files from the new generator
once and then add the comparison.) Do NOT golden-test the PNG bytes — OpenCV
encoder output may vary across versions; `render_texture` determinism is
already covered by the existing tests.

**Verify**: `uv run pytest tests/unit/test_marker_assets.py -q` → all pass.

### Step 3: Confirm a full regeneration is a no-op

Run `uv run python tools/gen_marker_assets.py` (defaults write into
`sim/models/`). Then `git diff --stat sim/models/`. Expected: either clean, or
ONLY `model.config` text diffs (description wording) and/or PNG byte diffs
from encoder differences. `model.sdf` MUST be diff-clean. If `model.config`
differs, commit the regenerated configs (they're generator-owned). If PNGs
differ, restore them (`git checkout -- 'sim/models/*/materials'`) — committed
textures are the flight-verified ones.

**Verify**: `git diff --exit-code sim/models/*/model.sdf` → exit 0.

### Step 4: Add `--ids` and a `just gen-markers` recipe

In `main()`, add `parser.add_argument("--ids", type=int, nargs="+",
default=list(MARKER_IDS), help="Marker ids to generate (DICT_4X4_50: 0-49)")`
and pass `tuple(args.ids)` to `generate_all`. Validate each id is in
`[0, 49]` (DICT_4X4_50 size); exit 2 with a clear message otherwise. Add a
`justfile` recipe following the file's existing pattern:

```
# Generate ArUco marker model assets (see docs/SIM.md)
gen-markers *args:
    uv run python tools/gen_marker_assets.py {{args}}
```

(match the real justfile's recipe idiom — copy the shape of a neighboring
tool-invoking recipe, including any `_run` wrapper it uses.)

**Verify**: `uv run python tools/gen_marker_assets.py --ids 3 --output-root /tmp/claude/markers_test`
→ writes `aruco_marker_3` tree; its `model.sdf` contains `emissive_map` and
`model://aruco_marker_3/`. Then `uv run python tools/gen_marker_assets.py --ids 99 --output-root /tmp/claude/markers_test`
→ exit 2 with a message naming the valid range.

### Step 5: Full gate

**Verify**: `just check` → exit 0.

## Test plan

- `test_generator_matches_committed_models` (step 2) — the regression lock.
- A test for `--ids` parsing / range validation (call `main(["--ids", "99",
  ...])` expecting `SystemExit(2)`), modeled on the existing tests in
  `tests/unit/test_marker_assets.py`.
- Existing determinism tests keep passing (update expectations where they
  pinned the old SDF).

## Done criteria

- [ ] `build_model_sdf(i) == sim/models/aruco_marker_<i>/model.sdf` for i in 0..2 (golden test passes)
- [ ] `rg emissive_map tools/gen_marker_assets.py` → at least one hit
- [ ] `git diff --exit-code sim/models/*/model.sdf` after a full regeneration → exit 0
- [ ] `just gen-markers` recipe exists; `--ids` works and validates range
- [ ] `just check` → exit 0
- [ ] `plans/README.md` status row updated

## STOP conditions

- The three committed `model.sdf` files differ from each other in structure
  beyond the marker id (they should be identical modulo `0`→`1`/`2`).
- Making the generator byte-identical requires changing a committed
  `model.sdf` — never do that; report instead.
- `just check` fails for a reason unrelated to your diff.

## Maintenance notes

- The committed models are the oracle. Any future change to marker rendering
  must be live-verified first (fly `09_aruco_hover_real`), THEN mirrored into
  the generator — the golden test forces the mirror step.
- Plan 072 (challenge authoring kit) builds on `--ids`; if you rename the
  flag, update that plan.
