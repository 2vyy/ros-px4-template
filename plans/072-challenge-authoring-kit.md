# Plan 072: Challenge authoring kit — spec-YAML world generator + the end-to-end playbook an agent follows from a rules document

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in "STOP conditions" occurs, stop and report — do not
> improvise. When done, update this plan's row in `plans/README.md` unless a
> reviewer told you they maintain the index.
>
> **Drift check (run first)**:
> `git diff --stat 6ce9aec..HEAD -- sim/worlds tools/ config/marker_maps docs/SIM.md justfile tests/unit/`
> On any mismatch with the "Current state" excerpts below, STOP.

## Status

- **Priority**: P1 (direction: this is the project's stated end-goal)
- **Effort**: M
- **Risk**: LOW (generator + docs; no flight-code changes)
- **Depends on**: plan 066 (`gen_marker_assets.py --ids` for marker ids > 2)
- **Category**: direction / dx
- **Planned at**: commit `6ce9aec`, 2026-07-16

## Why this matters

The project's goal: hand an agent a competition rules document and have it
independently build a scenario that represents the challenge and verify it.
Every ingredient exists — flight-verified world skeleton, marker generator,
marker maps, data-driven missions, scenario scaffold, capability registry —
but the connective tissue is tribal: worlds are hand-copied from
`default.sdf` (four near-duplicate SDF skeletons already exist and any typo
in the physics block breaks EKF timing, see plans/049), marker maps are
hand-synced to world poses (a silent mismatch = relocalization quietly
teleports the drone), and the ordered file loop lives in five different docs.
This plan adds the ONE missing tool (a world generator driven by a small
challenge-spec YAML, with the map generated from the same spec so they cannot
disagree) and ONE playbook document (`docs/CHALLENGES.md`) that walks the
whole loop with commands. Deliberately NOT added (scope-creep guard): no
mission-YAML generator (missions are the agent's actual authoring work and
the schema + `just mission sim` already validate them), no scenario
generator beyond the existing `just scenario-new`, no new abstractions in
`src/`.

## Current state

- `sim/worlds/`: `default.sdf` (88 lines, flight-verified baseline),
  `marker_field.sdf` (118), `landing_pad.sdf` (140), `obstacle_course.sdf`
  (246). `marker_field.sdf`'s header: "Physics, gravity, magnetic field,
  ground plane, light, and spherical coordinates are copied verbatim from the
  flight-verified default.sdf." Shared skeleton blocks (verbatim, in this
  order): `<physics type="ode">` (max_step_size 0.004, real_time_factor 1.0,
  real_time_update_rate 250), `<gravity>0 0 -9.8</gravity>`,
  `<magnetic_field>6e-06 2.3e-05 -4.2e-05</magnetic_field>`,
  `<atmosphere type="adiabatic"/>`, `<scene>`, the `ground_plane` model, the
  `sunUTC` directional light, `<spherical_coordinates>` (lat
  47.397971057728974, lon 8.546163739800146, ENU).
- Marker include idiom (`marker_field.sdf:102–106`):

  ```xml
  <include>
    <uri>model://aruco_marker_0</uri>
    <name>aruco_marker_0</name>
    <pose>8 0 0.005 0 0 0</pose>
  </include>
  ```

- Obstacle idiom (`obstacle_course.sdf:105+`, five pylons): static model,
  `<pose>2 1.5 1 0 0 0</pose>` (z = height/2), cylinder collision + visual
  `<cylinder><radius>0.3</radius><length>2</length></cylinder>`. docs/SIM.md
  notes "the origin climb column stays clear" — an authoring invariant.
- `config/marker_maps/marker_field.yaml` — the map format:

  ```yaml
  markers:
    0: {x: 8.0, y: 0.0, z: 0.0}
    1: {x: -6.0, y: 10.0, z: 0.0}
    2: {x: 0.0, y: -12.0, z: 0.0}
  ```

  Selected via marker_localizer's `marker_map_file` parameter; installed by
  `src/core/setup.py:20` glob (`config/marker_maps/*.yaml`) — new maps need
  NO setup.py change, but DO need a rebuild to reach the share dir.
- `docs/SIM.md` — world table, marker scale, boot-path and perception
  limitations (including the emissive_map constraint). 52 lines.
- Boot path for repo worlds (docs/SIM.md "Limitations"): `_start_gz_px4.sh`
  pre-starts a paused gz server on the repo SDF; any world file in
  `sim/worlds/` works with `just sim --world <name>` with no launch changes.
- The authoring loop today (spread across AGENTS.md, docs/SIM.md,
  docs/MISSIONS.md, plans/043, plans/054): marker models
  (`tools/gen_marker_assets.py`) → world SDF (hand-copy) → marker map
  (hand-sync) → mission YAML (`config/missions/`, validated by
  `just mission validate` / simulated by `just mission sim`) → optional
  param overlay → scenario (`just scenario-new <NN>_<name>`) →
  `tests/capabilities.toml` entry (`sim_world`/`sim_model`/`sim_vision`
  fields boot the declared config in e2e) → live verify (`just scenario`,
  `just test e2e`) → `just cap mark <id> sim`.
- `justfile` recipes delegate to `uv run python tasks.py ...` or tools
  directly; plan 066 adds `just gen-markers`.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Quality gate | `just check` | exit 0 |
| Generator tests | `uv run pytest tests/unit/test_gen_world.py -q` | all pass |
| Boot a generated world | `just sim --world <name> --gui` | READY verdict |
| Mission dry-run | `just mission sim <name>` | verdict, exit 0 |

## Scope

**In scope**:
- New `tools/gen_world.py` + `tests/unit/test_gen_world.py`
- New `sim/worlds/specs/` directory with `marker_field.yaml` (the golden
  round-trip spec) and one new example spec
- `config/marker_maps/` (generated outputs)
- New `docs/CHALLENGES.md`; one row/link added to `docs/SIM.md` and the
  Reference table in `AGENTS.md`/`README.md` if a natural slot exists
- `justfile`: one `gen-world` recipe

**Out of scope** (do NOT touch):
- `src/` — nothing in the flight stack changes.
- `sim/worlds/default.sdf` — the flight-verified baseline is never generated.
- Existing committed worlds other than confirming the marker_field round-trip
  (landing_pad and obstacle_course keep their hand-written files; converting
  them is optional follow-up, not this plan).
- Mission/scenario generators — explicitly rejected as abstraction creep.

## Git workflow

- Branch: `advisor/072-challenge-authoring-kit`
- Commit style: `feat(sim): gen_world.py challenge spec generator + docs/CHALLENGES.md playbook`
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Challenge spec format + `tools/gen_world.py`

Spec YAML (one file per challenge, in `sim/worlds/specs/<name>.yaml`):

```yaml
# Challenge spec: <one-line provenance, e.g. "rules doc section 3.2">
name: marker_field
markers:            # DICT_4X4_50 ids; z is implicit (0.005 surface lift)
  - {id: 0, x: 8.0, y: 0.0}
  - {id: 1, x: -6.0, y: 10.0}
  - {id: 2, x: 0.0, y: -12.0}
obstacles: []       # optional; type: cylinder|box, static only
# - {type: cylinder, name: pylon_1, x: 2.0, y: 1.5, radius: 0.3, height: 2.0}
# - {type: box, name: wall_1, x: 4.0, y: 0.0, size: [0.2, 3.0, 2.0]}
```

`tools/gen_world.py` (mirror `gen_marker_assets.py`'s structure: pure
builders, I/O only in `write_*`/`main`):

- `build_world_sdf(spec) -> str`: header comment (generated-by line + marker
  layout, mirroring `marker_field.sdf`'s header), then the skeleton blocks
  **verbatim from the committed `marker_field.sdf`** (read it, template only
  `<world name=...>`), then one obstacle `<model>` per obstacle (cylinder
  idiom verbatim from `obstacle_course.sdf`'s pylons, z-pose = height/2; box
  analogous), then one marker `<include>` per marker (idiom above, pose
  `{x} {y} 0.005 0 0 0`).
- `build_marker_map(spec) -> str`: the `config/marker_maps` format above,
  from the SAME spec dict (z: 0.0), with the header comment naming the spec
  file it came from.
- Validation (exit 2 with a clear message, matching the repo's usage-error
  convention): marker ids in [0, 49]; duplicate ids/names rejected; obstacle
  footprint must not intrude within 1.5 m of the origin (the "origin climb
  column stays clear" invariant — cylinder: dist(0,0)-radius, box: rectangle
  distance); world name must be a valid filename and not `default`.
- Consistency by construction: the SDF's includes and the map's ids come from
  one list, so they cannot disagree. Additionally check each referenced
  `sim/models/aruco_marker_<id>/` exists; if missing, the error message says
  to run `just gen-markers --ids <id>` (plan 066).
- `main()`: `--spec <path>` (required), `--worlds-dir` / `--maps-dir`
  overrides for tests. Writes `sim/worlds/<name>.sdf` and
  `config/marker_maps/<name>.yaml`; prints both paths and a reminder line:
  "rebuild (`just check`) to install the marker map; add a docs/SIM.md row".

`justfile`: `gen-world *args:` → `uv run python tools/gen_world.py {{args}}`
(copy the neighboring recipe idiom / plan 066's `gen-markers`).

**Verify**: `uv run python tools/gen_world.py --spec sim/worlds/specs/marker_field.yaml`
→ regenerates `sim/worlds/marker_field.sdf` and
`config/marker_maps/marker_field.yaml`; `git diff --exit-code
sim/worlds/marker_field.sdf config/marker_maps/marker_field.yaml` → exit 0.
(This is the acceptance bar: the committed, GUI-verified world IS the golden
output. If exact byte-identity for the header comment is awkward, adjust the
committed header ONCE to the generated form in this same commit — the
skeleton and includes must not change.)

### Step 2: Unit tests

`tests/unit/test_gen_world.py` (import via the tools-path idiom used by
`tests/unit/test_scenario_roster.py`):

- `test_marker_field_round_trip`: `build_world_sdf(spec) ==` committed
  `marker_field.sdf` bytes and `build_marker_map(spec) ==` committed map
  bytes (golden lock, same philosophy as plan 066).
- `test_physics_block_matches_default_world`: the generated SDF contains the
  exact `<physics>`...`</physics>` substring of `sim/worlds/default.sdf`
  (guards the EKF-timing-critical block independently of the golden file).
- `test_map_and_world_agree`: for a spec with markers 0/5/7, every
  `model://aruco_marker_<id>` include in the SDF has a map entry and vice
  versa.
- `test_origin_column_clear_rejected`: an obstacle at (0.5, 0) with radius
  0.3 → SystemExit(2) / validation error naming the invariant.
- `test_unknown_marker_model_names_gen_markers`: spec with id 7 and no
  `sim/models/aruco_marker_7` → error message contains `gen-markers`.

**Verify**: `uv run pytest tests/unit/test_gen_world.py -q` → all pass;
`just check` → exit 0.

### Step 3: One new example spec, booted live

Author `sim/worlds/specs/gate_run.yaml` (or similar): markers 0 and 3 plus
two pylons, generated end to end: `just gen-markers --ids 3`,
`just gen-world --spec sim/worlds/specs/gate_run.yaml`, `just check` (build
installs the new map), then `just sim --world gate_run` → READY, and
`just log topics` clean. `just stop`. Commit the spec + generated world +
map + `aruco_marker_3` model. Add its row to the `docs/SIM.md` world table.

**Verify**: READY verdict on the generated world; `just stop` clean.

### Step 4: `docs/CHALLENGES.md` — the rules-document-to-verified-scenario playbook

Write the playbook in the README's terse table style (house style: no em
dashes, no Unicode arrows). Sections:

1. **Input**: what to extract from a rules document (arena geometry, marker
   ids/positions, required maneuvers, time/altitude limits, scoring events).
2. **The loop** (ordered table: step, file(s), command, verify):
   claims first — decompose the rules doc into claim entries in
   `tests/capabilities.toml` (one composite per scored task with `source` +
   `params`, plus missing leaf claims; see docs/CLAIMS.md and the claims
   ladder spec section 5; `just cap plan <challenge>` is the live build
   order from here on) → spec YAML (`sim/worlds/specs/`) →
   `just gen-markers --ids ...` (if new
   ids) → `just gen-world --spec ...` → mission YAML in `config/missions/`
   (link docs/MISSIONS.md schema; validate with `just mission validate`,
   dry-run with `just mission sim <name>`) → param overlay if needed
   (`config/params/overlays/`) → scenario via `just scenario-new <NN>_<name>`
   (edit `done()`; real `detail` in `write_report`) →
   `tests/capabilities.toml` entry with `sim_world`/`sim_model`/`sim_vision`
   → `just scenario <name>` live → `just test e2e` → `just cap mark <id> sim`.
3. **Docs to update** (TOPICS.md only if topics changed; SIM.md world row;
   MISSIONS.md tables only if new behaviors/guards).
4. **Representable vs verifiable** (the honesty section — one paragraph
   each): the sim can REPRESENT arbitrary static geometry and marker layouts,
   but the stack can only VERIFY what it can sense and assert: perception is
   a single nadir camera (real pixels only with `--model x500_mono_cam_down`
   on a marker world; synthetic detections otherwise); obstacles are physical
   collision hazards but NOT perceived (no avoidance sensor exists — a
   challenge requiring reactive avoidance is out of template scope); no
   moving actors; physics is real-time only (world SDF is the sole speed
   authority, plans/065). Guards available for rules assertions live in
   docs/MISSIONS.md (plan 073 extends them).
5. **Worked example**: the step-3 spec, from "rules say two gates and a
   marker at 8 m" to `cap mark`.

Link `docs/CHALLENGES.md` from the README/AGENTS.md Reference table row
"Authoring a challenge from a rules doc".

**Verify**: `just check` → exit 0 (docs checkers, if any, stay green). A
cold read of CHALLENGES.md by the operator is the real acceptance.

## Test plan

- Unit: golden round-trip, physics-block pin, map/world agreement, origin
  column validation, missing-model message (step 2).
- Live: generated `gate_run` world boots to READY with clean topics (step 3).
- Docs: playbook walked once while producing the step-3 example (steps 3–4
  are deliberately the same work).

## Done criteria

- [ ] `just gen-world --spec sim/worlds/specs/marker_field.yaml` reproduces the committed world + map byte-identically
- [ ] `uv run pytest tests/unit/test_gen_world.py -q` → all pass
- [ ] A NEW spec-generated world boots: `just sim --world gate_run` → READY
- [ ] `docs/CHALLENGES.md` exists, covers the full loop with commands, and contains the representable-vs-verifiable section
- [ ] `docs/SIM.md` world table includes the new world
- [ ] `just check` → exit 0
- [ ] `plans/README.md` status row updated

## STOP conditions

- The marker_field round trip requires changing the SKELETON blocks or marker
  poses of the committed `marker_field.sdf` (header-comment-only adjustment
  is allowed, see step 1) — the committed world is GUI-verified (plan 043);
  report instead.
- The generated example world does not reach READY — do not debug the boot
  path (plans/049 owns it); report the verdict and logs.
- You find yourself designing a mission or scenario generator — that is the
  scope creep this plan explicitly rejects. Stop at the playbook.

## Maintenance notes

- `default.sdf` stays hand-written and boot-path byte-identical; the
  generator's physics block is pinned to it by unit test, so a deliberate
  physics change must update both (the test failure is the reminder).
- If landing_pad/obstacle_course are ever regenerated from specs, do it as
  its own change with a GUI look — they are currently hand-verified.
- Plan 073's new guards extend the "verifiable" vocabulary; when it lands,
  add them to CHALLENGES.md section 4.
