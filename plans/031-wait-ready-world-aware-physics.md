# Plan 031: `wait_ready` throttles physics for the actual world, not a hardcoded `/world/default`

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report - do not improvise. When done, update the status row for this plan
> in `plans/README.md` - unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat ead4cc6..HEAD -- tools/wait_ready.py tasks.py tests/unit/test_wait_ready.py`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: bug
- **Planned at**: commit `ead4cc6`, 2026-07-06

## Why this matters

`just sim --world <name> --speed <f<1.0>` is supposed to throttle Gazebo
physics after readiness. `tools/wait_ready.py` performs that throttle with a
`gz service` call whose service path is hardcoded to `/world/default/set_physics`.
For any world other than `default` the call targets a nonexistent service,
silently returns False, and the run proceeds unthrottled with only a WARN line.
This matters more once plan 043 (competition worlds) lands: every custom world
plus `--speed` combination silently ignores the speed request.

## Current state

- `tools/wait_ready.py` - readiness gate; contains the hardcoded path.
- `tasks.py` - invokes `wait_ready.py` at three sites (lines 530, 675, 737);
  only the sim path (line 530) passes `--speed`. The sim command already has
  the world name in scope (its `--world` flag, default `"default"`).
- `tests/unit/test_wait_ready.py` - existing CliRunner tests to model after.

The hardcoded call (`tools/wait_ready.py:120-137`):

```python
def _set_physics_speed(speed: float) -> bool:
    update_rate = int(speed * 250)
    try:
        r = subprocess.run(
            [
                "gz",
                "service",
                "-s",
                "/world/default/set_physics",
                ...
```

The CLI entry (`tools/wait_ready.py:147-151`):

```python
@app.command()
def main(
    timeout: int = typer.Option(180, "--timeout", help="Seconds before giving up"),
    speed: float = typer.Option(1.0, "--speed", help="Physics speed factor (must not exceed 1.0)"),
) -> None:
```

Call site in `tasks.py` (line 530, inside the `sim` command):

```python
["uv", "run", "python", "tools/wait_ready.py", "--timeout", str(timeout),
```

(read the surrounding lines in `tasks.py` to see the full argv; `--speed` is
appended there when relevant).

Important behavior to preserve: at `speed == 1.0` the `set_physics` call is
**skipped entirely** (see the comment block at `wait_ready.py:182-187` - calling
it at speed 1.0 re-initializes the integrator and can destabilize an airborne
vehicle). Do not change that skip.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Unit tests | `uv run pytest tests/unit/test_wait_ready.py -q` | all pass |
| Lint | `uv run ruff check tools/wait_ready.py tests/unit/test_wait_ready.py` | exit 0 |
| Lint tasks.py (not covered by `just check`) | `uv run ruff check tasks.py` | exit 0 |
| Full gate | `just check` | exit 0 |

## Scope

**In scope**:
- `tools/wait_ready.py`
- `tasks.py` (only the `wait_ready.py` invocation in the `sim` command path)
- `tests/unit/test_wait_ready.py`

**Out of scope**:
- The other two `wait_ready.py` call sites (`tasks.py:675` hw, `:737` e2e) -
  hw has no Gazebo world; e2e pins `--speed 1.0` where the throttle is skipped.
  Leave them; the new option defaults to `"default"` so they stay correct.
- `sim/launch/sim_full.launch.py` - world selection there is already correct.

## Git workflow

- Branch: `advisor/031-wait-ready-world`
- Commit style: `fix(wait_ready): throttle physics on the launched world, not /world/default`
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Parameterize the world in `_set_physics_speed`

Change the signature to `_set_physics_speed(speed: float, world: str) -> bool`
and build the service path as `f"/world/{world}/set_physics"`.

Add a `--world` option to `main` mirroring the existing options:

```python
    world: str = typer.Option("default", "--world", help="Gazebo world name (for set_physics)"),
```

and pass it through at the call site inside `main`
(`elif _set_physics_speed(speed):` becomes `elif _set_physics_speed(speed, world):`).

**Verify**: `uv run ruff check tools/wait_ready.py` -> exit 0

### Step 2: Pass the world from the sim command in tasks.py

In the `sim` command in `tasks.py`, extend the `wait_ready.py` argv at line 530
with `"--world", world` (the sim command's world variable; confirm its exact
name by reading the surrounding function - it is the value of the `--world`
CLI option, default `"default"`).

**Verify**: `uv run ruff check tasks.py` -> exit 0

### Step 3: Unit test the service path

Add to `tests/unit/test_wait_ready.py` (model after the existing
`test_ready_requires_standby_gate` style - CliRunner + `unittest.mock.patch`):

- `test_set_physics_uses_world_arg`: patch `wait_ready.subprocess.run` to
  capture argv and return an object with `stdout="data: true"`; call
  `wait_ready._set_physics_speed(0.5, "marker_field")` directly; assert
  `"/world/marker_field/set_physics"` is in the captured argv.
- `test_speed_below_one_passes_world_through`: CliRunner invoke with
  `["--timeout", "5", "--speed", "0.5", "--world", "foo"]`, patching the three
  gate functions to True and `_set_physics_speed` with a mock; assert it was
  called with `(0.5, "foo")`.

**Verify**: `uv run pytest tests/unit/test_wait_ready.py -q` -> all pass (2 new)

### Step 4: Full gate

**Verify**: `just check` -> exit 0

## Test plan

Covered in Step 3: two new tests in `tests/unit/test_wait_ready.py`
(happy-path path formatting; CLI plumbs `--world` to the throttle call).
Pattern: the existing tests in the same file.

## Done criteria

- [ ] `uv run pytest tests/unit/test_wait_ready.py -q` passes with 2 new tests
- [ ] `rg -n '"/world/default/set_physics"' tools/wait_ready.py` returns no matches
- [ ] `rg -n '"--world"' tasks.py` shows the sim-path wait_ready argv includes it
- [ ] `just check` exits 0
- [ ] `git status` shows only in-scope files modified
- [ ] `plans/README.md` status row updated

## STOP conditions

- The `tasks.py` sim command does not have the world name in scope where
  wait_ready is invoked (drift in tasks.py structure).
- Any existing test in `test_wait_ready.py` starts failing.
- The speed==1.0 skip block would need modification (it must not).

## Maintenance notes

- Plan 043 adds new worlds; this plan is what makes `--speed` work with them.
- Reviewer: confirm the default `"default"` keeps the hw/e2e call sites
  (which do not pass `--world`) byte-identical in behavior.
