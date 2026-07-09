# Plan 024: `just scenario status [name]` prints a single scenario's verdict

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving on. If
> anything in "STOP conditions" occurs, stop and report. When done, update this
> plan's row in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 0f93f0e..HEAD -- tasks.py tools/e2e_report.py tools/cli_verdict.py tests/scenarios/_common.py`
> If any changed, compare excerpts to live code before proceeding.

## Status

- **Priority**: P3
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: direction
- **Planned at**: commit `0f93f0e`, 2026-06-22

## Why this matters

After a scenario runs, its result is durably written to
`logs/scenario_<name>.json`, but the only ways to read it back are scrolling the
console or `cat`-ing JSON. `tools/e2e_report.py` formats verdicts but only
across **all** `scenario_*.json` at once. A one-liner that prints a single
scenario's rich verdict — pass/fail plus the detail fields (e.g. waypoint error,
hold time, fail reason) — and exits 0/1 closes the debugging loop for
"what happened in that last run?" without jq. It reuses formatting that already
exists, so it is ~20 LOC.

**This is a direction plan**: low cost, low stakes. If the maintainer finds the
console output sufficient, mark REJECTED.

## Current state

- The report shape (`tests/scenarios/_common.py:98-115`, `write_report`):
  ```python
  report = {"scenario": name, "passed": passed,
            "elapsed_s": round(elapsed_s, 2), "detail": detail}
  out = _LOG_DIR / f"scenario_{name}.json"
  ```
  So files are `logs/scenario_<name>.json` with keys `scenario`, `passed`,
  `elapsed_s`, `detail` (a dict, with an optional `reason` on failures).
- Formatting already exists: `tools/cli_verdict.py:35-38` `format_scenario(name,
  passed, detail, elapsed_s) -> str` returns `"PASS|FAIL <name> <detail> <Ns>"`,
  and `tools/e2e_report.py:19-24` `_detail_str(passed, detail)` turns the detail
  dict into the human string. `e2e_report.build_block` already reads these files.
- The `scenario` command is `tasks.py:869-917`. The `log` sub-app
  (`tools/log_query.py`, registered as `log`) hosts read-only query commands like
  `topics`/`summary`/`tail`. A `scenario status` could live as either a new
  top-level command or a `log` sub-command — see Step 1.
- `ExitCode` (`tools/cli_verdict.py:16-22`): `OK=0`, `FAIL=1`, `USAGE=2`.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Run new unit tests | `uv run pytest tests/unit/test_scenario_status.py -q` | all pass |
| Full unit suite | `uv run pytest tests/unit/ -q` | all pass |
| Lint | `uv run ruff check tools/scenario_status.py tests/unit/test_scenario_status.py` | exit 0 |
| Typecheck | `uv run ty check tools/ tests/unit` | exit 0 |
| Smoke (with a fixture file) | see Step 3 | prints a PASS/FAIL line, correct exit |

## Scope

**In scope**:
- `tools/scenario_status.py` (create) — a pure `format_scenario_status(log_dir,
  name) -> tuple[str, int]` helper (reads one `scenario_<name>.json`, or the most
  recent if `name` is omitted) plus a thin CLI entry.
- `tasks.py` (modify) — wire it as a command (e.g. `scenario-status`, mirroring
  how `status` shells to `tools/status.py`).
- `tests/unit/test_scenario_status.py` (create) — test the pure helper.
- `AGENTS.md` "Logs" section (modify) — one line documenting the command.

**Out of scope**:
- `tools/e2e_report.py`, `tools/cli_verdict.py` — reuse their helpers; do not
  change them.
- `_common.write_report` — the JSON shape is fixed; do not change it.

## Git workflow

- Branch: `advisor/024-scenario-status`
- Conventional commit (e.g. `feat(scenario): scenario-status prints one run's verdict`).
- Do NOT push or open a PR unless instructed.

## Steps

### Step 1: Pure helper in `tools/scenario_status.py`

Write `format_scenario_status(log_dir: Path, name: str | None) -> tuple[str,
int]`:
- If `name` is given, read `log_dir / f"scenario_{name}.json"`.
- If `name` is omitted, pick the most recently modified `scenario_*.json` in
  `log_dir`.
- If no matching file exists, return `("no scenario report found ...",
  int(ExitCode.USAGE))`.
- Otherwise parse it and return `(format_scenario(s["scenario"], s["passed"],
  _detail_str(s["passed"], s.get("detail", {})), s.get("elapsed_s", 0.0)),
  int(ExitCode.OK) if s["passed"] else int(ExitCode.FAIL))`.

Import `format_scenario` and `ExitCode` from `cli_verdict`, and `_detail_str`
from `e2e_report` (both on `sys.path` via `tests/conftest.py` for tests and via
`tasks.py`'s `sys.path.append(tools)` at runtime). Add a `main()` that prints the
line and `sys.exit`s the code, so the module is runnable directly.

**Verify**: `uv run ruff check tools/scenario_status.py` → exit 0.

### Step 2: Wire the command in `tasks.py`

Mirror the existing `status` command (`tasks.py:920-923`), which shells to a
tool. Add e.g.:
```python
@app.command("scenario-status")
def scenario_status(name: str = typer.Argument("", help="Scenario name; default: most recent.")):
    """Print the verdict of one scenario's last run from logs/scenario_<name>.json."""
    args = ["uv", "run", "python", "tools/scenario_status.py"]
    if name:
        args.append(name)
    res = subprocess.run(args, cwd=str(ROOT))
    raise typer.Exit(res.returncode)
```

**Verify**: `grep -n "scenario-status\|scenario_status" tasks.py` → shows the
command.

### Step 3: Test the pure helper

Create `tests/unit/test_scenario_status.py` (model on `test_e2e_report.py`). Use
`tmp_path`:
- Write a passing `scenario_x.json` → `format_scenario_status(tmp_path, "x")`
  returns a string starting `PASS` and exit code 0.
- Write a failing `scenario_y.json` with `detail={"reason": "timeout"}` →
  string starts `FAIL`, contains `timeout`, exit code 1.
- Empty dir → message + exit code 2.
- Two files with different mtimes, `name=None` → picks the newer (set mtimes via
  `os.utime`).

**Verify**: `uv run pytest tests/unit/test_scenario_status.py -q` → all pass.

### Step 4: Document

Add one line to the `AGENTS.md` "Logs (Agent Query Workflow)" section noting
`just scenario-status [name]` for a single run's verdict.

**Verify**: `grep -n "scenario-status" AGENTS.md` → shows the line.

## Test plan

- `tests/unit/test_scenario_status.py` with the four cases above.
- `uv run pytest tests/unit/ -q` → all pass.

## Done criteria

ALL must hold:

- [ ] `tools/scenario_status.py` exists with a pure `format_scenario_status` returning `(line, exit_code)`
- [ ] `uv run python tasks.py scenario-status <name>` prints the verdict and exits 0 (pass) / 1 (fail) / 2 (missing)
- [ ] `uv run pytest tests/unit/test_scenario_status.py -q` passes (≥4 cases)
- [ ] `uv run pytest tests/unit/ -q` exits 0
- [ ] `uv run ruff check tools/scenario_status.py tests/unit/test_scenario_status.py` exits 0
- [ ] `uv run ty check tools/ tests/unit` exits 0
- [ ] `grep -n "scenario-status" AGENTS.md` shows the doc line
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report if:

- The `scenario_<name>.json` shape in `_common.write_report` differs from
  "Current state".
- `format_scenario` / `_detail_str` signatures changed.
- Importing `cli_verdict` / `e2e_report` from the new module fails at runtime
  (the `sys.path.append(tools)` in `tasks.py` is the mechanism; for the runnable
  `main()` path the module is invoked as `tools/scenario_status.py` from `ROOT`,
  so it must add `tools/` to its own `sys.path` if run standalone — handle it).

## Maintenance notes

- If the scenario report JSON gains fields, `_detail_str` already ignores
  unknown keys except `reason`; no change needed unless you want to surface them.
- Reviewer: confirm exit codes (0/1/2) match the repo's `ExitCode` convention so
  scripts/CI can branch on them.
