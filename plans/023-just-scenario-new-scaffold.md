# Plan 023: `just scenario new <name>` scaffolds a runnable scenario stub

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving on. If
> anything in "STOP conditions" occurs, stop and report. When done, update this
> plan's row in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 0f93f0e..HEAD -- tasks.py tests/scenarios/_common.py tests/scenarios/03_waypoint.py`
> If any changed, compare excerpts to live code before proceeding.

## Status

- **Priority**: P3
- **Effort**: M
- **Risk**: LOW
- **Depends on**: none
- **Category**: direction
- **Planned at**: commit `0f93f0e`, 2026-06-22

## Why this matters

Authoring a new live scenario today means copy-pasting an existing one (~50-200
LOC) and editing it. The newer scenarios already converged on a clean base class
(`_common.Scenario`, used by `03_waypoint.py` in ~54 LOC), so the boilerplate is
predictable — exactly what a scaffold command removes. `just scenario new <name>`
that writes a correct, runnable `Scenario` stub turns "copy, rename, fix imports,
remember the capability entry" into "edit the predicate." This serves the stated
"headless e2e testing solely from CLI" goal by lowering the cost of adding a new
acceptance test.

**This is a direction plan**: the maintainer may feel 5 scenarios is too few to
justify a generator, or prefer a documented copy-this-file convention. If so,
mark REJECTED. Trade-off: one small command + a template file vs. continued
copy-paste.

## Current state

- The base class (`tests/scenarios/_common.py:118-189`): `Scenario` is an ABC with
  `name: str`, `timeout_s: float = 60.0`, abstract `make_node()` and `done()`,
  optional `fail_reason()` / `report_detail()`, and `run()` that handles rclpy
  init/teardown, timeout, exception capture, and `write_report(...)`.
  `run_main(scenario_cls)` is the entry point.
- The exemplar to mirror (`tests/scenarios/03_waypoint.py`, full file is ~54
  lines): imports `from _common import Scenario, run_main`, defines a `_Node(Node)`
  that subscribes to a status topic, a `WaypointScenario(Scenario)` with
  `name`/`timeout_s`/`make_node`/`done`/`report_detail`, and
  `if __name__ == "__main__": run_main(WaypointScenario)`.
- The `scenario` command (`tasks.py:869-917`) runs scenarios; the `test`
  command's `scenario` type also exists. Scenarios live in
  `tests/scenarios/NN_<name>.py`. Existing numbers: 01,02,03,05,06 (04 is unused).
- Per `AGENTS.md` "Code changes", a new scenario also needs a
  `tests/capabilities.toml` entry; the scaffold should print a reminder (and may
  optionally append a stub entry, but printing the exact TOML to add is safer —
  see Step 2).
- `tasks.py` ruff per-file note: `tests/scenarios/**` allows `N999` (numeric
  filenames are run as scripts, not imported).

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Scaffold a scenario | `uv run python tasks.py scenario-new 99_smoke` | writes `tests/scenarios/99_smoke.py`, prints next steps |
| Lint the generated file | `uv run ruff check tests/scenarios/99_smoke.py` | exit 0 |
| Confirm it imports/parses | `uv run python -c "import ast; ast.parse(open('tests/scenarios/99_smoke.py').read())"` | no error |
| Run new unit tests | `uv run pytest tests/unit/test_scenario_scaffold.py -q` | all pass |

(Use `scenario-new` as the command name if a Typer sub-command under `scenario`
is awkward — `scenario` is currently a single command taking a positional
`name`. See Step 1 for the exact wiring choice.)

## Scope

**In scope**:
- `tests/scenarios/_template.py.txt` (create) — a template stub (NOT a `.py`, so
  pytest/ruff do not try to import a placeholder; `.txt` keeps it inert). Or embed
  the template string in the command — your choice; the `.txt` form is easier to
  read and test.
- `tasks.py` (modify) — add the scaffold command + a pure `render_scenario(name)`
  helper importable for tests.
- `tests/unit/test_scenario_scaffold.py` (create) — test the pure renderer.
- `docs/MISSIONS.md` or `AGENTS.md` (modify) — one line pointing at the command
  in the "adding a scenario" guidance.

**Out of scope**:
- Existing scenarios (01/02/03/05/06) — do not refactor them.
- `_common.Scenario` — reuse as-is; do not change the base class.
- Auto-editing `tests/capabilities.toml` with real values — print the snippet to
  add instead (writing a half-valid capability row risks breaking
  `scenario_sim_configs()` which drives e2e scheduling).

## Git workflow

- Branch: `advisor/023-scenario-scaffold`
- Conventional commit (e.g. `feat(scenario): just scenario-new scaffolds a Scenario stub`).
- Do NOT push or open a PR unless instructed.

## Steps

### Step 1: Add a pure `render_scenario(name)` + a scaffold command to `tasks.py`

Write a pure function `render_scenario(name: str) -> str` that returns the stub
source for a scenario named `name`, modeled exactly on `03_waypoint.py`: imports
`Scenario, run_main` from `_common`, a `_Node(Node)` subscribing to
`/drone/mission_status` (`px4_ros_msgs/MissionStatus`) as a sensible default, a
`<CamelName>Scenario(Scenario)` with `name = "<name>"`, a `timeout_s`, a
`make_node`, a `done` predicate (with a `# TODO: define your pass condition`
marker), and `report_detail`, ending in `if __name__ == "__main__":
run_main(<CamelName>Scenario)`. Derive the class name from `name` (strip a
leading `NN_`, CamelCase the rest).

Add a command (e.g. `@app.command("scenario-new")`) taking `name: str =
typer.Argument(...)` that:
- refuses to overwrite an existing `tests/scenarios/<name>.py`
  (`raise typer.Exit(int(ExitCode.USAGE))` if it exists),
- writes `render_scenario(name)` to `tests/scenarios/<name>.py`,
- prints the path and a "next steps" block: add a `tests/capabilities.toml`
  entry (show the exact stub TOML lines to paste), then run
  `just scenario <name>`.

**Verify**: `uv run python tasks.py scenario-new 99_smoke` writes the file and
prints next steps; `uv run ruff check tests/scenarios/99_smoke.py` → exit 0;
re-running the command on the same name exits 2 without overwriting.

### Step 2: Test the renderer

Create `tests/unit/test_scenario_scaffold.py`. Import `render_scenario` (it is in
`tasks.py`; `tests/conftest.py` does NOT put the repo root on `sys.path`, so to
import it either move `render_scenario` into a small `tools/` module and import
that, or test via `ast.parse` of the generated file). Simplest robust approach:
put `render_scenario` in a new `tools/scenario_scaffold.py` (on `sys.path` via
conftest) and have `tasks.py` import it. Then test:
- `render_scenario("99_smoke")` output `ast.parse`s without error.
- It contains `from _common import Scenario, run_main`, `class SmokeScenario`,
  `name = "99_smoke"`, and `run_main(SmokeScenario)`.
- The class name derivation strips the leading `99_`.

**Verify**: `uv run pytest tests/unit/test_scenario_scaffold.py -q` → all pass.

### Step 3: Clean up the smoke file and document

Delete the throwaway `tests/scenarios/99_smoke.py` you generated for verification
(`git status` must not show it). Add one line to the "adding a scenario"
guidance (in `AGENTS.md` "Code changes" → "New scenarios" bullet, or
`docs/MISSIONS.md`) pointing at `just scenario-new <name>`.

**Verify**: `git status --porcelain tests/scenarios/` shows no stray `99_smoke.py`;
`grep -rn "scenario-new" AGENTS.md docs/` shows the doc reference.

## Test plan

- `tests/unit/test_scenario_scaffold.py` as in Step 2 (≥3 assertions: parses,
  contains the key symbols, class-name derivation).
- `uv run pytest tests/unit/ -q` → all pass.
- Manual: a freshly scaffolded file passes `ruff check` and `ast.parse`.

## Done criteria

ALL must hold:

- [ ] `uv run python tasks.py scenario-new <name>` creates a `ruff`-clean, `ast`-parseable `tests/scenarios/<name>.py` modeled on `03_waypoint.py`
- [ ] Re-running on an existing name exits 2 and does not overwrite
- [ ] The command prints the `tests/capabilities.toml` snippet + `just scenario <name>` next step
- [ ] `uv run pytest tests/unit/test_scenario_scaffold.py -q` passes
- [ ] `uv run pytest tests/unit/ -q` exits 0
- [ ] No throwaway smoke file is left committed
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report if:

- `_common.Scenario` / `run_main` signatures differ from "Current state".
- `03_waypoint.py` is no longer a valid template (the base-class pattern changed).
- The generated stub fails `ruff check` for a reason you cannot fix within the
  template (e.g. a new lint rule) — report rather than disabling lints broadly.

## Maintenance notes

- Keep `render_scenario` output in sync with the `_common.Scenario` API; the
  Step 2 `ast.parse` test guards against syntactically broken templates but not
  against API drift — add an assertion if the base class gains required members.
- Reviewer: confirm the scaffold does not auto-write into `capabilities.toml`
  (it prints the snippet) and that the default subscribed topic is a reasonable
  starting point an author will replace.
