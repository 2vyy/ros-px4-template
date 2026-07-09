# Plan 022: Mission YAML gets an editor schema for autocomplete + validation

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving on. If
> anything in "STOP conditions" occurs, stop and report. When done, update this
> plan's row in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 0f93f0e..HEAD -- config/missions/ src/core/ros_px4_template_core/lib/mission/ tools/mission_cli.py`
> If any changed, compare excerpts to live code before proceeding.

## Status

- **Priority**: P3
- **Effort**: S
- **Risk**: LOW
- **Depends on**: plans/016-just-mission-validate-list-show.md (reuses its `mission` sub-app + registry access)
- **Category**: direction
- **Planned at**: commit `0f93f0e`, 2026-06-22

## Why this matters

Mission authoring is the template's headline use case, and it is hand-written
YAML. Plan 016 adds CLI validation (`just mission validate`), which catches
errors *after* you save. A JSON Schema catches them *as you type* in any
schema-aware editor (the repo already ships `.cursor/` tooling) — autocomplete
for `behavior`/`guard` names, structural validation of `states`/`transitions`/
`safety`. Because the valid behavior and guard names live in the registry
(`known_behaviors()` / `known_guards()`), the schema can be **generated** from the
single source of truth rather than hand-maintained, so it never drifts. This is a
small, additive ergonomic win grounded in the existing data-driven design.

**This is a direction plan**: the maintainer may prefer no schema (one more
artifact) or a different editor-integration approach. If so, mark it REJECTED and
keep 016. The trade-off is one generated file + a `$schema` comment per mission
vs. live editor feedback.

## Current state

- Missions: `config/missions/{demo,hover,marker_hover,search_relocalize}.yaml`.
  Schema shape is documented in `docs/MISSIONS.md:28-42`:
  ```
  mission:
    initial: <state>
    states: { <name>: {behavior: <name>, params: {...}}, ... }
    safety:      [ {guard: <name>, params: {...}, to: <state>}, ... ]   # optional
    transitions: [ {from: <state>, guard: <name>, params: {...}, to: <state>}, ... ]
    terminal: [<state>, ...]   # optional
  ```
- Valid names come from `lib/mission/registry.py`: `known_behaviors()` returns
  `{hold, follow_waypoints, search_lawnmower, center_on_marker, goto_origin}`;
  `known_guards()` returns `{armed_at_altitude, waypoints_done, reached,
  hold_complete, search_complete, marker_fresh, marker_stable, marker_lost,
  geofence_breach, estimate_invalid, inputs_stale}`. **Generate the enums from
  these functions; do not hardcode.**
- Plan 016 created `tools/mission_cli.py` (a `mission` Typer sub-app) that already
  imports the registry and adds `src/core` to `sys.path`. Reuse it.
- No `jsonschema` dependency is currently declared (`pyproject.toml`
  dependencies). You do NOT need it at runtime — editors consume the schema. Only
  add a dev-time validation test if you can do it without a new runtime dep (see
  Test plan; `jsonschema` may be added to the `dev` dependency group only).

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Generate the schema | `uv run python tasks.py mission schema > schemas/mission.schema.json` | writes valid JSON |
| Validate it is JSON | `uv run python -c "import json; json.load(open('schemas/mission.schema.json'))"` | no error |
| Run schema tests | `uv run pytest tests/unit/test_mission_schema.py -q` | all pass |
| Lint | `uv run ruff check tools/mission_cli.py tests/unit/test_mission_schema.py` | exit 0 |

## Scope

**In scope**:
- `tools/mission_cli.py` (modify) — add a `schema` command that prints a JSON
  Schema built from the registry, and a pure `build_schema()` helper.
- `schemas/mission.schema.json` (create) — the generated, committed schema.
- `config/missions/*.yaml` (modify) — add one `# yaml-language-server: $schema=../../schemas/mission.schema.json` comment line at the top of each (keep existing description comments).
- `tests/unit/test_mission_schema.py` (create) — assert the schema accepts every
  real mission and rejects an unknown behavior/guard.
- `docs/MISSIONS.md` (modify) — a short "Editor schema" note.

**Out of scope**:
- `lib/mission/` — read the registry; do not change it.
- Adding `jsonschema` as a **runtime** dependency. Editor consumption needs no
  Python dep.

## Git workflow

- Branch: `advisor/022-mission-json-schema`
- Conventional commit (e.g. `feat(mission): generate a JSON Schema for editor validation`).
- Do NOT push or open a PR unless instructed.

## Steps

### Step 1: Add `build_schema()` + a `schema` command to `tools/mission_cli.py`

Add a pure helper that returns a `dict` JSON Schema (draft 2020-12) for the
mission document, with `behavior` constrained to `enum: sorted(known_behaviors())`
and `guard` to `enum: sorted(known_guards())`, and the `states`/`transitions`/
`safety`/`terminal`/`initial` structure from `docs/MISSIONS.md:28-42`. Then a
`@app.command("schema")` that prints `json.dumps(build_schema(), indent=2)`.

Keep `build_schema()` pure (returns the dict) so the test can call it directly.

**Verify**: `uv run python tasks.py mission schema | python -c "import sys,json; json.load(sys.stdin)"` → no error.

### Step 2: Generate and commit the schema file

```
mkdir -p schemas
uv run python tasks.py mission schema > schemas/mission.schema.json
```

**Verify**: `uv run python -c "import json; json.load(open('schemas/mission.schema.json'))"` → no error; the file contains the behavior/guard enums.

### Step 3: Reference the schema from each mission

Add a `# yaml-language-server: $schema=../../schemas/mission.schema.json` line as
the **first** line of each `config/missions/*.yaml`, above the existing
description comment. (The `yaml-language-server` directive is what the VS Code /
Neovim / Cursor YAML extensions read.)

**Verify**: `grep -l "yaml-language-server" config/missions/*.yaml` → lists all 4
files; `uv run python tasks.py mission validate demo` still prints OK (the comment
does not affect the loader).

### Step 4: Test the schema accepts real missions and rejects bad ones

Create `tests/unit/test_mission_schema.py`. If you add `jsonschema` to the `dev`
dependency group (`pyproject.toml [dependency-groups] dev`), validate each real
mission doc against `build_schema()` and assert a doc with an unknown behavior
fails. If you prefer no new dev dep, instead assert structural properties of the
schema dict directly (e.g. the behavior enum equals `sorted(known_behaviors())`,
the guard enum equals `sorted(known_guards())`, required keys present). Either is
acceptable; prefer real `jsonschema` validation if the dep is allowed.

**Verify**: `uv run pytest tests/unit/test_mission_schema.py -q` → all pass.

### Step 5: Document it

Add an "Editor schema" subsection to `docs/MISSIONS.md` explaining the `$schema`
comment and that `just mission schema` regenerates `schemas/mission.schema.json`
when behaviors/guards change.

**Verify**: `grep -n "schema" docs/MISSIONS.md` → shows the new note.

## Test plan

- `tests/unit/test_mission_schema.py`: every real mission validates; an
  unknown-behavior doc fails; the enums match the registry.
- `uv run pytest tests/unit/ -q` → all pass.

## Done criteria

ALL must hold:

- [ ] `just mission schema` (via `uv run python tasks.py mission schema`) emits valid JSON with behavior/guard enums from the registry
- [ ] `schemas/mission.schema.json` is committed and is valid JSON
- [ ] All 4 `config/missions/*.yaml` carry the `yaml-language-server` `$schema` comment and still `validate` OK
- [ ] `uv run pytest tests/unit/test_mission_schema.py -q` passes
- [ ] `uv run pytest tests/unit/ -q` exits 0
- [ ] No new **runtime** dependency added (a `dev`-group `jsonschema` is allowed)
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report if:

- Plan 016 has not landed (`tools/mission_cli.py` absent) — this plan reuses it;
  build 016 first or implement the registry import here, but do not duplicate the
  sub-app.
- The registry function names/returns differ from "Current state".
- Generating the schema would require a runtime `jsonschema` dependency — it must
  not; editors consume the static file.

## Maintenance notes

- Regenerate `schemas/mission.schema.json` (`just mission schema > ...`) whenever
  a behavior or guard is added/removed; the test in Step 4 will fail if the
  committed file drifts from the registry, which is the intended guard.
- Reviewer: confirm the enums are generated, not hardcoded, and that the schema
  path in the `$schema` comments resolves from `config/missions/`.
