# Plan 016: `just mission` validates, lists, and describes missions without booting the sim

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving on. If
> anything in "STOP conditions" occurs, stop and report — do not improvise. When
> done, update this plan's row in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 0f93f0e..HEAD -- tasks.py src/core/ros_px4_template_core/lib/mission/ config/missions/`
> If any changed, compare the "Current state" excerpts to the live code before
> proceeding; on a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: LOW
- **Depends on**: none
- **Category**: dx / direction
- **Planned at**: commit `0f93f0e`, 2026-06-22

## Why this matters

The template's headline promise is "smart mission planning, defining, and
headless e2e testing solely from CLI." Mission definitions are pure data
(`config/missions/*.yaml`) and the loader already fully validates them
(`lib/mission/loader.py` raises `MissionError` for unknown behaviors, guards,
initial states, or transition targets). **But that validation only ever runs
inside the `mission_manager` node, at sim runtime.** So today, the only way to
discover a typo in a mission YAML — a misspelled behavior, a transition to a
nonexistent state — is to boot the entire Gazebo + PX4 SITL + XRCE stack (~16-30
seconds) and watch the node die. That is the single biggest friction point in
mission *defining*.

The loader is `rclpy`-free pure Python, so we can expose it as an instant CLI:
`just mission validate <name>` runs in under a second on a bare checkout with no
ROS, no build, no sim. This is the "adjacent possible" — the validation already
exists; it just is not reachable from the command line. This plan adds a
`mission` sub-app (`list`, `validate`, `show`) mirroring the existing `cap` and
`log` sub-apps.

## Current state

### The CLI sub-app pattern to mirror

`tasks.py` registers two sub-apps from `tools/`:
- `tasks.py:153-166`:
  ```python
  # Ensure tools/ is on path to import sub-apps
  sys.path.append(str(ROOT / "tools"))
  from capabilities import app as cap_app, scenario_sim_configs
  from log_summary import build_run_summary
  from cli_verdict import ExitCode, format_not_ready, format_ready, format_stopped
  import sim_cleanup
  import bag_recorder
  import ulog_retrieve
  import skein_analyze
  from log_query import app as log_app

  # Register sub-apps
  app.add_typer(log_app, name="log", help="Query, merge, tail, or view logs/status/topics.")
  app.add_typer(cap_app, name="cap", help="Manage verified capabilities registry.")
  ```
  Each sub-app is a `typer.Typer()` defined in its own `tools/*.py` module.
- The `justfile` has no per-recipe entry for `cap`/`log`/`mission`; instead a
  generic recipe forwards (look at `justfile` — `cap *args:` and `log *args:`
  each call `@just _run cap "$@"`). You will add an equivalent `mission` recipe.

### The loader you will call

`src/core/ros_px4_template_core/lib/mission/loader.py`:
```python
class MissionError(ValueError):
    """Raised when a mission document is structurally invalid."""

def load_mission_file(path: str | Path) -> Mission:
    p = Path(path)
    doc = yaml.safe_load(p.read_text(encoding="utf-8"))
    return load_mission_dict(doc, base_dir=p.resolve().parents[2])
```
`load_mission_file` validates structure AND resolves `path_file` waypoints (so a
missing path file surfaces here too, as a `FileNotFoundError`, not a
`MissionError`). The returned `Mission` (`lib/mission/types.py`) has fields:
`initial: str`, `states: dict[str, StateDef]`, `safety: tuple[TransitionDef,...]`,
`transitions: tuple[TransitionDef,...]`, `terminal: frozenset[str]`. A `StateDef`
has `.name`, `.behavior`, `.params`; a `TransitionDef` has `.src`, `.guard`,
`.params`, `.dst`.

The registry exposes the valid names (`lib/mission/registry.py`):
```python
def known_behaviors() -> set[str]: ...
def known_guards() -> set[str]: ...
```
Current registered behaviors: `hold`, `follow_waypoints`, `search_lawnmower`,
`center_on_marker`, `goto_origin`. Current guards: `armed_at_altitude`,
`waypoints_done`, `reached`, `hold_complete`, `search_complete`, `marker_fresh`,
`marker_stable`, `marker_lost`, `geofence_breach`, `estimate_invalid`,
`inputs_stale`. (Do not hardcode these — call `known_behaviors()`/
`known_guards()` so the list stays correct.)

### Import-path note (critical)

`load_mission_file` lives under `src/core/ros_px4_template_core/...`. That path is
**not** on `sys.path` for a bare `uv run python tasks.py` invocation (it is for
pytest, via `tests/conftest.py:7` which inserts `src/core`). Your new tool module
**must add `src/core` to `sys.path` before importing the loader**, exactly like
conftest does, so `just mission validate` works without a colcon build. The
entire mission library is `rclpy`-free (lib/ is required to stay rcl-free per
`AGENTS.md`), so this import pulls in no ROS.

### The missions on disk

```
config/missions/demo.yaml
config/missions/hover.yaml
config/missions/marker_hover.yaml
config/missions/search_relocalize.yaml
```
Each begins with a `# comment` line describing it, then `mission:` mapping. Example
`config/missions/hover.yaml`:
```yaml
# Hover-only: climb to target altitude and hold. Used by 01_arm_takeoff / 02_hover_hold.
mission:
  initial: hover
  states:
    hover: {behavior: hold, params: {z: 3.0}}
  terminal: [hover]
```

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Run new unit tests | `uv run pytest tests/unit/test_mission_cli.py -q` | all pass |
| Run full unit suite | `uv run pytest tests/unit/ -q` | all pass (no regressions) |
| Lint the new module | `uv run ruff check tools/mission_cli.py tests/unit/test_mission_cli.py` | exit 0 |
| Typecheck | `uv run ty check tools/ tests/unit` | exit 0 |
| Smoke the CLI (list) | `uv run python tasks.py mission list` | table of 4 missions, exit 0 |
| Smoke the CLI (validate ok) | `uv run python tasks.py mission validate hover` | `OK hover ...`, exit 0 |
| Smoke the CLI (validate bad) | `uv run python tasks.py mission validate __nope__` | error line, exit 2 |

Run the CLI via `uv run python tasks.py mission ...` (NOT `just mission ...`)
during development: the `just` wrapper sources ROS or enters distrobox, which the
mission CLI does not need. The `just mission` recipe is for end users.

## Suggested executor toolkit

- Model the new module on `tools/capabilities.py` (a small `typer.Typer()`
  sub-app) and the loader-driven validation on `tests/unit/test_mission_loader.py`
  (it already exercises `load_mission_dict` happy/error paths).

## Scope

**In scope** (create/modify only these):
- `tools/mission_cli.py` (create) — the `mission` Typer sub-app + pure helpers.
- `tests/unit/test_mission_cli.py` (create) — unit tests for the helpers.
- `tasks.py` (modify) — import and register the sub-app (2-3 lines, mirroring
  the `cap`/`log` registration).
- `justfile` (modify) — add a `mission *args:` recipe mirroring `cap`/`log`.
- `README.md` (modify) — add one `just mission validate <name>` line to the
  "Everyday commands" block.
- `docs/MISSIONS.md` (modify) — add a short "Validate from the CLI" subsection.

**Out of scope** (do NOT touch):
- `lib/mission/loader.py`, `engine.py`, `registry.py`, `types.py` — reuse them
  as-is; do not change validation logic here.
- `config/missions/*.yaml` — read them, do not edit.
- `nodes/mission_manager.py` — runtime loading is unrelated to this CLI.

## Git workflow

- Branch: `advisor/016-just-mission-cli`
- Commit per logical unit (module+tests, then wiring, then docs); conventional
  commits (e.g. `feat(mission): just mission validate/list/show without booting the sim`).
- Do NOT push or open a PR unless instructed.

## Steps

### Step 1: Create `tools/mission_cli.py` with pure helpers + a Typer sub-app

Build a module that (a) adds `src/core` to `sys.path` at import, (b) exposes pure
helper functions that are unit-testable without Typer, and (c) wraps them in a
`typer.Typer()` named `app` so `tasks.py` can `add_typer` it.

Target shape (fill in details to match repo style — double quotes, `from
__future__ import annotations`, google-style docstrings):

```python
"""`just mission` — list, validate, and describe mission YAML without a sim."""
from __future__ import annotations

import sys
from pathlib import Path

import typer

_ROOT = Path(__file__).resolve().parents[1]
# Make the rclpy-free mission library importable on a bare checkout (mirrors
# tests/conftest.py); the loader does NOT need a colcon build or ROS.
sys.path.insert(0, str(_ROOT / "src" / "core"))

from ros_px4_template_core.lib.mission.loader import MissionError, load_mission_file  # noqa: E402
from ros_px4_template_core.lib.mission.registry import known_behaviors, known_guards  # noqa: E402
from ros_px4_template_core.lib.mission.types import Mission  # noqa: E402

MISSIONS_DIR = _ROOT / "config" / "missions"

app = typer.Typer(help="List, validate, and describe mission YAML graphs.")


def mission_path(name: str) -> Path:
    """Resolve a mission name ('hover' or 'hover.yaml' or a path) to a file path."""
    p = Path(name)
    if p.suffix == ".yaml" and p.exists():
        return p
    return MISSIONS_DIR / (name if name.endswith(".yaml") else f"{name}.yaml")


def list_missions() -> list[tuple[str, str]]:
    """Return [(name, first_comment_line)] for every config/missions/*.yaml."""
    out: list[tuple[str, str]] = []
    for f in sorted(MISSIONS_DIR.glob("*.yaml")):
        first = ""
        for line in f.read_text(encoding="utf-8").splitlines():
            if line.startswith("#"):
                first = line.lstrip("# ").rstrip()
                break
        out.append((f.stem, first))
    return out


def validate_mission(name: str) -> tuple[bool, str]:
    """Return (ok, message). Never raises. message describes the error if not ok."""
    path = mission_path(name)
    if not path.is_file():
        return (False, f"no such mission file: {path}")
    try:
        m = load_mission_file(path)
    except MissionError as e:
        return (False, f"invalid: {e}")
    except FileNotFoundError as e:  # path_file referenced by the mission is missing
        return (False, f"missing referenced file: {e}")
    except Exception as e:  # malformed YAML, bad types
        return (False, f"{type(e).__name__}: {e}")
    return (True, f"{len(m.states)} states, initial={m.initial}, terminal={sorted(m.terminal)}")


def describe_mission(m: Mission) -> str:
    """Return a multi-line human summary of a loaded Mission (states + transitions)."""
    ...  # states with their behavior+params, safety+mission transitions with guard, terminal set
```

The three Typer commands wrap these:
- `@app.command("list")` → print each `name — comment` (use `rich` if you like;
  `rich` is already a dependency). Exit 0.
- `@app.command("validate")` taking `name: str = typer.Argument(...)` → call
  `validate_mission`; print `OK <name> <message>` or `FAIL <name> <message>`;
  raise `typer.Exit(0)` on ok, `typer.Exit(2)` on failure (2 == USAGE, matching
  the repo's `ExitCode.USAGE` convention for bad input — you may import
  `ExitCode` from `cli_verdict`, which is on `sys.path` via tasks.py, but in the
  standalone module add `sys.path.insert(0, str(_ROOT / "tools"))` first, or just
  use the literal `2`).
- `@app.command("show")` taking `name: str` → load and print `describe_mission`;
  on a load error, print the error and `typer.Exit(2)`.

Keep `list`/`validate`/`show` thin; put all logic in the pure helpers so the
tests target the helpers, not Typer.

**Verify**: `uv run ruff check tools/mission_cli.py` → exit 0; `uv run python -c "import sys; sys.path.insert(0,'tools'); import mission_cli; print(mission_cli.list_missions())"` → prints the 4 missions with comments.

### Step 2: Register the sub-app in `tasks.py`

After the existing sub-app imports (`tasks.py:162`) add:
```python
from mission_cli import app as mission_app
```
and after the existing `app.add_typer(...)` calls (`tasks.py:166`) add:
```python
app.add_typer(mission_app, name="mission", help="List, validate, and describe mission YAML.")
```

**Verify**: `uv run python tasks.py mission list` → prints the 4-mission table,
exit 0. `uv run python tasks.py mission validate hover` → `OK hover ...`, exit 0.
`uv run python tasks.py mission validate __nope__` → `FAIL ... no such mission
file ...`, exit code 2 (`echo $?` after the command).

### Step 3: Add the `mission` recipe to the `justfile`

Mirror the existing `cap`/`log` recipes (look at `justfile` for the exact form;
they read `@just _run cap "$@"`). Add near them:
```
# List, validate, or describe mission YAML graphs (no sim needed)
mission *args:
    @just _run mission "$@"
```

**Verify**: `grep -n "^mission" justfile` → shows the recipe. (Do not run `just
mission` itself to verify unless ROS/distrobox is available; the `uv run python
tasks.py mission ...` checks in Step 2 are the authoritative behavioral test.)

### Step 4: Write unit tests in `tests/unit/test_mission_cli.py`

Model the file after `tests/unit/test_mission_loader.py`. Test the pure helpers
(no Typer, no ROS). Cover:
- `list_missions()` returns all 4 real missions (`hover`, `demo`, `marker_hover`,
  `search_relocalize`), each with a non-empty comment string.
- `validate_mission("hover")` returns `(True, ...)`.
- `validate_mission("__does_not_exist__")` returns `(False, "no such mission file...")`.
- `validate_mission` on a tmp file with an unknown behavior returns
  `(False, "invalid: ...")` — build the bad YAML with `tmp_path` and point
  `mission_path` at it (or call `load_mission_file` indirectly by writing the file
  into a temp dir and passing the full `.yaml` path). Reuse the doc-builder style
  from `test_mission_loader.py`.
- `describe_mission` of a loaded `hover` mission contains `"hover"` and
  `"hold"` (the state and its behavior).

Use `tmp_path` fixtures for the malformed cases so you never write into
`config/missions/`.

**Verify**: `uv run pytest tests/unit/test_mission_cli.py -q` → all pass.

### Step 5: Document the new command

- `README.md` "Everyday commands" block: add one line (coordinate with plan 017
  which also edits this block — if 017 already landed, just insert the line;
  if not, add it and 017 will preserve it):
  ```
  just mission validate <name>      # validate a mission YAML in <1s, no sim
  ```
- `docs/MISSIONS.md`: add a short subsection (after the loader paragraph around
  line 44-46) titled "Validate from the CLI" explaining `just mission list`,
  `just mission validate <name>`, and `just mission show <name>`, and that it
  runs the same loader the node uses but without booting anything.

**Verify**: `grep -n "just mission" README.md docs/MISSIONS.md` → shows the new
references.

## Test plan

- New file `tests/unit/test_mission_cli.py` with the cases listed in Step 4
  (≥6 tests), modeled on `tests/unit/test_mission_loader.py`.
- The malformed-mission cases must use `tmp_path`, never the real
  `config/missions/`.
- Verification: `uv run pytest tests/unit/ -q` → all pass including the new file;
  the three CLI smokes in Step 2 produce the expected exit codes.

## Done criteria

ALL must hold:

- [ ] `uv run pytest tests/unit/ -q` exits 0 with the new `test_mission_cli.py` passing
- [ ] `uv run ruff check tools/mission_cli.py tests/unit/test_mission_cli.py` exits 0
- [ ] `uv run ty check tools/ tests/unit` exits 0
- [ ] `uv run python tasks.py mission list` lists all 4 missions, exit 0
- [ ] `uv run python tasks.py mission validate hover` prints OK, exit 0
- [ ] `uv run python tasks.py mission validate __nope__` prints a failure, exit 2
- [ ] `grep -n "^mission" justfile` shows the recipe
- [ ] `grep -n "just mission" README.md docs/MISSIONS.md` shows the docs
- [ ] Only the in-scope files are modified
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report if:

- Importing `ros_px4_template_core.lib.mission.loader` after inserting `src/core`
  on `sys.path` raises `ModuleNotFoundError` for an `rclpy`/ROS module — that
  would mean the loader is no longer rcl-free (a regression elsewhere); do not
  work around it by requiring a colcon build.
- `load_mission_file`'s signature or `Mission` fields differ from "Current state"
  (the library drifted).
- The `cap`/`log` sub-app registration pattern in `tasks.py:153-166` is not as
  excerpted (registration mechanism changed).

## Maintenance notes

- When a new behavior or guard is added to the registry, `just mission validate`
  automatically accepts it (it calls `known_behaviors()`/`known_guards()`); no
  change needed here. Plan 022 (mission JSON Schema) can call `known_behaviors()`/
  `known_guards()` the same way, or reuse this module's helpers.
- If `just mission show` grows a graph/FSM visualization later, keep the pure
  `describe_mission` separate from rendering so it stays unit-testable.
- Reviewer: confirm the `sys.path` insert targets `src/core` (not the package
  dir) and that no test writes into `config/missions/`.
