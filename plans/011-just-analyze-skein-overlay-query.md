# Plan 011: `just analyze [<run>]` — overlay + query a recorded run through skein

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**:
> `git diff --stat 34932bb..HEAD -- tasks.py justfile tools/bag_recorder.py`
> If any of those changed since this plan was written, compare the "Current
> state" excerpts against the live code before proceeding; on a mismatch, treat
> it as a STOP condition. This plan depends on plans **009 and 010** being merged
> (they create `logs/runs/<id>/bag/` and `logs/runs/<id>/session.ulg`). Confirm
> `tools/bag_recorder.py` and `tools/ulog_retrieve.py` both exist on HEAD; if not,
> STOP.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: LOW-MED (additive command; shells out to a separate `skein` project, writes only under `logs/`; touches no launch/teardown lifecycle)
- **Depends on**: `plans/009-*.md`, `plans/010-*.md` (both merged — they produce the artifacts this consumes)
- **Category**: direction (integration enablement)
- **Planned at**: commit `34932bb`, 2026-06-22

## Why this matters

Plans 009 + 010 make `just sim` leave a complete skein input pair per run:
`logs/runs/<id>/bag/<name>.mcap` (the ROS 2 bag) and `logs/runs/<id>/session.ulg`
(the matching PX4 ULog). But nothing in the template *uses* them yet — a user
must hand-type a long `skein overlay …` invocation with absolute paths. This plan
adds **`just analyze [<run>]`**: it finds the latest (or named) run's artifacts,
runs skein's **stable** `overlay` to write `logs/runs/<id>/aligned.mcap` (the
canonical cross-clock timeline), and optionally runs skein `query` over it. This
is follow-up **#3** of the integration design at
`/home/ivy/Projects/skein/docs/template-integration-design.md` (§4), and it
resolves the design's open-question 2 (how the template invokes skein) with the
recommended low-coupling mechanism: **invoke skein as its own `uv` project via a
subprocess** — `uv run --project <skein_dir> skein …` — so the ROS-coupled
template environment and skein's ROS-free analysis environment stay separate (no
skein dependency is added to the template's `pyproject.toml`).

Scope is the **stable** skein surface only (`overlay`, `query`). The graded
surface (`delta`, `reports`, `parity`, `live --grade`) is a later, hardware-gated
phase — out of scope here (design §5/§6).

## Current state

Files involved:

- `tasks.py` — the typer task runner (`#!/usr/bin/env uv run`, Python ≥ 3.12).
  - `ROOT = Path(__file__).resolve().parent`; `LOG_DIR = ROOT / "logs"`
    (`tasks.py:29-30`). The template lives at `/home/ivy/Projects/ros-px4-template`,
    so `ROOT.parent` is `/home/ivy/Projects`.
  - `_load_dotenv()` loads `.env` into `os.environ` at import (`tasks.py:37-52`),
    so an optional `SKEIN_DIR` override is available via `os.environ.get`.
  - `_get_clean_env()` returns an env with uv/venv stripped from PATH
    (`tasks.py:73-88`) — use it for the skein subprocess so the template's
    `VIRTUAL_ENV` doesn't confuse `uv run --project`.
  - `from cli_verdict import ExitCode, …` is already imported (`tasks.py:157`);
    reuse `ExitCode.USAGE` / `ExitCode.FAIL` for error exits, matching `sim()`.
  - Commands are `@app.command()` methods; sub-apps are registered with
    `app.add_typer(...)` (`tasks.py:162-163`). There is **no** `analyze` command
    today. The simplest matching pattern is a single new `@app.command()` (model
    its option/typer style on `sim()` at `tasks.py:450-462`).
  - `tools/` is on `sys.path` (`tasks.py:154`) and sub-modules are imported by
    bare name (`import sim_cleanup`, `import bag_recorder`, `import ulog_retrieve`).
    Add `import skein_analyze` the same way.

- `tools/bag_recorder.py` (from 009) defines `RUNS_DIR = LOG_DIR / "runs"` and the
  per-run layout: `logs/runs/<YYYYmmdd_HHMMSS>/` with a `latest` symlink, and the
  bag recorded under `logs/runs/<id>/bag/` (a `ros2 bag` **directory** containing
  `metadata.yaml` + a single `*.mcap`, typically `bag_0.mcap`).

- `tools/ulog_retrieve.py` (from 010) writes `logs/runs/<id>/session.ulg`.

- `justfile` — recipes delegate through `_run` to `uv run tasks.py <cmd>`
  (`justfile:12-20`). Existing recipe shape to mirror (`justfile:30-36`):
  ```
  # Boot the sim stack detached, wait until ready, print a verdict, and return
  sim *args:
      @just _run sim {{args}}

  # Exhaustive cold teardown of the whole stack (no process survives)
  stop:
      @just _run stop
  ```

- The **skein** project lives at the sibling path `/home/ivy/Projects/skein`
  (confirmed). Its console script is `skein` (`[project.scripts] skein =
  "skein.cli:app"`). Verified working invocation from this machine:
  `uv run --project /home/ivy/Projects/skein skein --help` → prints usage.
  The two stable verbs and their **exact** signatures (verified via `--help`):
  - `skein overlay --bag <PATH> --ulog <PATH> --out <PATH>` — `--out` is
    **required**; `--bag` and `--ulog` are each optional (at least one needed).
    Writes the canonical aligned MCAP to `--out`.
  - `skein query <ARTIFACT> [-c/--channel TEXT] [--where TEXT] [--stats]
    [--from TEXT] [--to TEXT]` — `<ARTIFACT>` is a **positional** path to the
    aligned MCAP; `--stats` prints per-channel aggregates instead of rows.
  - skein's golden fixtures (present in the skein repo, usable for an end-to-end
    smoke without ROS or a sim): `tests/fixtures/golden/session.mcap` and
    `tests/fixtures/golden/session.ulg`.

Conventions to match:
- Python ≥ 3.12, `from __future__ import annotations`, type hints.
- Tool logic lives in `tools/<name>.py` as small pure/injectable functions so
  `tests/unit/test_<name>.py` can test it without side effects (see
  `tools/bag_recorder.py` + `tests/unit/test_bag_recorder.py`,
  `tools/ulog_retrieve.py` + `tests/unit/test_ulog_retrieve.py` — the structural
  patterns for this plan's new module and test).
- Errors that are the user's fault exit `ExitCode.USAGE`; runtime failures exit
  `ExitCode.FAIL` (see `sim()`).

## Commands you will need

| Purpose            | Command                                                              | Expected on success                |
|--------------------|----------------------------------------------------------------------|------------------------------------|
| Lint new file      | `uv run ruff check tools/skein_analyze.py`                           | exit 0; "All checks passed!"       |
| Typecheck          | `uv run ty check tools/ --exclude tools/gcs_heartbeat.py`            | exit 0; "All checks passed!"       |
| New test only      | `uv run pytest tests/unit/test_skein_analyze.py -q`                  | all pass                           |
| Full unit suite    | `uv run pytest tests/unit/ -q --tb=short --ignore=tests/unit/test_scenario_verdict.py` | all pass            |
| Skein smoke (live) | `uv run --project /home/ivy/Projects/skein skein overlay --bag /home/ivy/Projects/skein/tests/fixtures/golden/session.mcap --ulog /home/ivy/Projects/skein/tests/fixtures/golden/session.ulg --out /tmp/_analyze_smoke.mcap` | writes `/tmp/_analyze_smoke.mcap` (exit 0) |

Note: `tests/unit/test_scenario_verdict.py` fails to *collect* without `rclpy`
(pre-existing) — always pass `--ignore=tests/unit/test_scenario_verdict.py` for
the full suite and note it. `just check`'s ruff gate lints `tools/` and `tests/`
(covers your new files) but not `tasks.py`; do not clean pre-existing `tasks.py`
lint findings.

## Scope

**In scope** (the only files you should modify or create):

- `tools/skein_analyze.py` (create) — pure helpers: resolve skein dir, resolve run
  dir, discover the bag `*.mcap`, build the `overlay`/`query` argv.
- `tasks.py` (modify) — `import skein_analyze`; add the `analyze` `@app.command()`.
- `justfile` (modify) — add the `analyze` recipe.
- `tests/unit/test_skein_analyze.py` (create) — unit tests for the helpers.
- `plans/README.md` (modify) — status row.

**Out of scope** (do NOT touch):

- `pyproject.toml` — do **not** add skein (or any) dependency. skein is invoked as
  a separate `uv` project via subprocess; that separation is the whole point.
- `tools/bag_recorder.py`, `tools/ulog_retrieve.py`, `tools/sim_cleanup.py` — read
  `bag_recorder.RUNS_DIR` if convenient, but do not modify these.
- The skein repo at `/home/ivy/Projects/skein` — never edit it; only invoke it.
- Graded skein surface: `delta`, `reports`, `parity`, `live`, `--grade`,
  `--gate-file`, reference marks, `refs/` — all deferred (design §5/§6).
- The sim/teardown lifecycle (`sim()`, `_teardown()`, `hw()`, e2e).

## Git workflow

- Branch: `advisor/011-just-analyze-skein-overlay-query`.
- Conventional commit, e.g. `feat(analyze): just analyze runs skein overlay/query over a recorded run`.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Create `tools/skein_analyze.py` (pure helpers)

Create the module with small, unit-testable functions. Target shape:

```python
#!/usr/bin/env python3
"""Helpers to run skein over a recorded run's artifacts (bag + ULog).

skein is a SEPARATE uv project (ROS-free); we invoke it as a subprocess via
`uv run --project <skein_dir> skein …` rather than importing it, to keep the
template's ROS-coupled env and skein's analysis env apart. These helpers build
the argv and resolve paths; tasks.py runs them.
"""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUNS_DIR = ROOT / "logs" / "runs"


class AnalyzeError(Exception):
    """A user-facing problem (missing run/artifact/skein dir). tasks.py maps this
    to a USAGE exit with the message."""


def resolve_skein_dir(skein_dir: str | None = None) -> Path:
    """The skein project dir: explicit arg, else $SKEIN_DIR, else the sibling
    ../skein next to this template. Must contain a pyproject.toml."""
    raw = skein_dir or os.environ.get("SKEIN_DIR", "").strip()
    path = Path(raw) if raw else ROOT.parent / "skein"
    if not (path / "pyproject.toml").is_file():
        raise AnalyzeError(
            f"skein project not found at {path} "
            "(set SKEIN_DIR or place skein beside this repo)."
        )
    return path


def resolve_run_dir(run: str, *, runs_dir: Path | None = None) -> Path:
    """Resolve 'latest' (the logs/runs/latest symlink) or a run id to its dir."""
    base = runs_dir or RUNS_DIR
    run_dir = base / run
    resolved = run_dir.resolve() if run_dir.is_symlink() else run_dir
    if not resolved.is_dir():
        raise AnalyzeError(
            f"no run at {run_dir} — record one with `just sim` first "
            "(runs live under logs/runs/<id>/)."
        )
    return resolved


def find_bag_mcap(run_dir: Path) -> Path | None:
    """The single *.mcap inside the run's ros2 bag dir (logs/runs/<id>/bag/), or
    None if absent."""
    bag_dir = run_dir / "bag"
    if not bag_dir.is_dir():
        return None
    mcaps = sorted(bag_dir.glob("*.mcap"))
    return mcaps[0] if mcaps else None


def overlay_argv(skein_dir: Path, *, bag: Path | None, ulog: Path | None, out: Path) -> list[str]:
    argv = ["uv", "run", "--project", str(skein_dir), "skein", "overlay", "--out", str(out)]
    if bag is not None:
        argv += ["--bag", str(bag)]
    if ulog is not None:
        argv += ["--ulog", str(ulog)]
    return argv


def query_argv(
    skein_dir: Path,
    artifact: Path,
    *,
    channel: str | None = None,
    where: str | None = None,
    stats: bool = False,
) -> list[str]:
    argv = ["uv", "run", "--project", str(skein_dir), "skein", "query", str(artifact)]
    if channel:
        argv += ["-c", channel]
    if where:
        argv += ["--where", where]
    if stats:
        argv += ["--stats"]
    return argv
```

**Verify**: `uv run ruff check tools/skein_analyze.py` → exit 0;
`uv run ty check tools/ --exclude tools/gcs_heartbeat.py` → exit 0.

### Step 2: Add the `analyze` command to `tasks.py`

Add `import skein_analyze` next to the other `tools/` imports. Add a new command
(model the typer style on `sim()`):

```python
@app.command()
def analyze(
    run: str = typer.Argument("latest", help="Run id under logs/runs/, or 'latest'."),
    query: str = typer.Option("", "--query", "-q", help="Run `skein query --where <expr>` on the aligned MCAP after overlay."),
    channel: str = typer.Option("vehicle_local_position", "--channel", "-c", help="Channel for --query."),
    stats: bool = typer.Option(False, "--stats", help="Per-channel aggregates for --query."),
):
    """Overlay a recorded run's bag + ULog onto one timeline with skein, writing
    logs/runs/<run>/aligned.mcap. With --query, also query that aligned MCAP.

    skein is invoked as a separate uv project (uv run --project). Override its
    location with SKEIN_DIR (default: ../skein beside this repo).
    """
    try:
        skein_dir = skein_analyze.resolve_skein_dir()
        run_dir = skein_analyze.resolve_run_dir(run)
    except skein_analyze.AnalyzeError as e:
        print(f"Error: {e}", file=sys.stderr)
        raise typer.Exit(int(ExitCode.USAGE)) from None

    bag = skein_analyze.find_bag_mcap(run_dir)
    ulog = run_dir / "session.ulg"
    ulog = ulog if ulog.is_file() else None
    if bag is None and ulog is None:
        print(
            f"Error: run {run_dir.name} has neither a bag (logs/runs/<id>/bag/*.mcap) "
            "nor a session.ulg — did it record? (see plans 009/010)",
            file=sys.stderr,
        )
        raise typer.Exit(int(ExitCode.USAGE))
    if ulog is None:
        print("Warning: no session.ulg for this run — overlaying bag only.", file=sys.stderr)
    if bag is None:
        print("Warning: no bag for this run — overlaying ULog only.", file=sys.stderr)

    out = run_dir / "aligned.mcap"
    env = _get_clean_env()
    print(f"Overlaying {run_dir.name} -> {out.relative_to(ROOT)}")
    res = subprocess.run(
        skein_analyze.overlay_argv(skein_dir, bag=bag, ulog=ulog, out=out),
        cwd=str(ROOT),
        env=env,
    )
    if res.returncode != 0:
        print("skein overlay failed.", file=sys.stderr)
        raise typer.Exit(int(ExitCode.FAIL))

    if query:
        res = subprocess.run(
            skein_analyze.query_argv(skein_dir, out, channel=channel, where=query, stats=stats),
            cwd=str(ROOT),
            env=env,
        )
        if res.returncode != 0:
            print("skein query failed.", file=sys.stderr)
            raise typer.Exit(int(ExitCode.FAIL))
```

(`subprocess`, `sys`, `os`, `typer`, `ExitCode`, `_get_clean_env`, `ROOT` are all
already imported/defined in `tasks.py`.)

**Verify**:
`uv run python -c "import sys; sys.path.insert(0,'tools'); import skein_analyze; print('ok')"` → `ok`;
and `uv run python tasks.py analyze --help` → prints the analyze help (this also
confirms `tasks.py` still imports cleanly). If `tasks.py` fails to import here due
to a missing ROS module, that is a STOP condition — report it.

### Step 3: Add the `analyze` recipe to `justfile`

Mirror the `sim` recipe (`justfile:30-32`):

```
# Analyze a recorded run with skein (overlay bag+ULog; optional --query)
analyze *args:
    @just _run analyze {{args}}
```

**Verify**: `grep -n "^analyze" justfile` → matches. (Do not run `just analyze`
live here — `_run` needs ROS/distrobox; the command itself is exercised via
`uv run python tasks.py analyze` in Step 2 and the smoke in Step 5.)

### Step 4: Unit-test `skein_analyze` (hermetic — no skein/ROS needed)

Create `tests/unit/test_skein_analyze.py`, modeled on
`tests/unit/test_ulog_retrieve.py`. Cover at least:

1. `overlay_argv` builds the expected list: starts with
   `["uv","run","--project",<skein>,"skein","overlay","--out",<out>]` and includes
   `--bag`/`--ulog` only when those args are non-None (test all three: both, bag
   only, ulog only).
2. `query_argv` includes the positional artifact, and `-c`/`--where`/`--stats`
   only when provided.
3. `resolve_skein_dir` returns the path when `<dir>/pyproject.toml` exists (make a
   fake dir under `tmp_path` with a `pyproject.toml`, pass it explicitly), and
   raises `AnalyzeError` when it does not.
4. `resolve_run_dir` returns the dir for an existing run id (create
   `tmp_path/runs/<id>/`, pass `runs_dir=tmp_path/runs`), and raises
   `AnalyzeError` for a missing run.
5. `find_bag_mcap` returns the `*.mcap` inside `<run_dir>/bag/` (create
   `run_dir/bag/bag_0.mcap`), and `None` when the `bag/` dir or any `*.mcap` is
   absent.

**Verify**: `uv run pytest tests/unit/test_skein_analyze.py -q` → all pass.

### Step 5: End-to-end skein smoke (you CAN run this — skein is ROS-free)

This proves the overlay invocation actually works against real fixtures, without
ROS or a sim. Run the "Skein smoke (live)" command from the table:

```bash
uv run --project /home/ivy/Projects/skein skein overlay \
  --bag /home/ivy/Projects/skein/tests/fixtures/golden/session.mcap \
  --ulog /home/ivy/Projects/skein/tests/fixtures/golden/session.ulg \
  --out /tmp/_analyze_smoke.mcap
```

**Verify**: exit 0 and `/tmp/_analyze_smoke.mcap` exists and is non-empty
(`ls -l /tmp/_analyze_smoke.mcap`). Then optionally:
`uv run --project /home/ivy/Projects/skein skein query /tmp/_analyze_smoke.mcap -c vehicle_local_position --stats`
→ prints aggregate rows (exit 0). If the skein project or fixtures are absent in
this environment, report that this smoke was skipped (don't fail) — but the unit
tests in Step 4 are then the binding verification.

### Step 6: Run the unit suite

**Verify**: `uv run pytest tests/unit/ -q --tb=short --ignore=tests/unit/test_scenario_verdict.py`
→ all pass.

## Test plan

- New `tests/unit/test_skein_analyze.py` (hermetic), covering the 5 helper cases
  in Step 4 — these are the binding unit verification and need neither skein nor
  ROS.
- The Step 5 smoke is a one-shot manual check that the real `skein overlay`
  invocation works on golden fixtures; it is **not** a committed test (committed
  unit tests must not depend on the sibling skein repo).
- No unit test for the `tasks.py analyze` command body (it orchestrates
  subprocesses); its argv construction is covered by the helper tests and its
  import-cleanliness by `uv run python tasks.py analyze --help`.
- Verification: `uv run pytest tests/unit/ -q --ignore=tests/unit/test_scenario_verdict.py` → all pass.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `tools/skein_analyze.py` exists; `uv run ruff check tools/skein_analyze.py` exits 0.
- [ ] `uv run ty check tools/ --exclude tools/gcs_heartbeat.py` exits 0.
- [ ] `tests/unit/test_skein_analyze.py` exists; `uv run pytest tests/unit/test_skein_analyze.py -q` passes.
- [ ] `uv run pytest tests/unit/ -q --ignore=tests/unit/test_scenario_verdict.py` passes.
- [ ] `grep -n "import skein_analyze" tasks.py` matches; `grep -n "def analyze" tasks.py` matches.
- [ ] `uv run python tasks.py analyze --help` exits 0 and shows the analyze options.
- [ ] `grep -n "^analyze" justfile` matches.
- [ ] `grep -n "skein" pyproject.toml` returns **nothing** (no dependency added).
- [ ] `tools/bag_recorder.py`, `tools/ulog_retrieve.py`, `tools/sim_cleanup.py`, `pyproject.toml` unchanged (`git diff --stat HEAD~1..HEAD` shows only the in-scope files).
- [ ] No files outside the in-scope list are modified (`git status`).
- [ ] `plans/README.md` status row for 011 updated.

Live (SITL, end-to-end) verification — perform if a distrobox sim is available;
otherwise report deferred (do not fake it):

- [ ] `just sim --overlay auto_arm`, fly a few seconds, `just stop`.
- [ ] `just analyze` (no args → latest run) writes `logs/runs/<id>/aligned.mcap`.
- [ ] `just analyze latest --query 'z < -1' --stats` prints query output over the
      aligned MCAP.

## STOP conditions

Stop and report back (do not improvise) if:

- `tools/bag_recorder.py` or `tools/ulog_retrieve.py` is missing on HEAD (plans
  009/010 not merged) — this plan depends on them.
- The "Current state" excerpts for `tasks.py` / `justfile` don't match the live
  code (drift since `34932bb`).
- `uv run python tasks.py analyze --help` fails because `tasks.py` cannot import
  in this environment (e.g. a sub-module needs `rclpy`) — report the import error;
  do not work around it by gutting imports.
- The skein CLI signature differs from "Current state" (e.g. `skein overlay` no
  longer accepts `--bag/--ulog/--out`) when you run the Step 5 smoke — report the
  actual `skein overlay --help` output.
- Implementing this appears to require adding a dependency to `pyproject.toml` or
  editing the skein repo.
- A step's verification fails twice after a reasonable fix attempt.

## Maintenance notes

For whoever owns this next:

- **Invocation mechanism**: `uv run --project <skein_dir> skein …` (subprocess,
  separate env). `SKEIN_DIR` overrides the default sibling `../skein`. If skein is
  later published/pinned, this is the one place to switch to `uvx --from <spec>`
  or a pinned console script — keep it in `tools/skein_analyze.py`.
- **Re-overlay cost**: `analyze` re-runs `overlay` every call (it overwrites
  `aligned.mcap`). If runs get large and re-querying becomes slow, add a
  "skip overlay if aligned.mcap newer than the bag" shortcut — deliberately not
  done now to keep behavior obvious.
- **Graded surface (Phase 2, deferred)**: `delta`/`reports`/`parity`/`live --grade`
  need calibrated gates + a `refs/` reference library + flown reference marks, and
  skein's gating is Tier-3 (field-calibration pending). Adding them to `analyze`
  is a separate, hardware-gated plan — do not fold them in here.
- **Reviewer focus**: confirm no skein dependency was added to `pyproject.toml`;
  confirm the skein subprocess uses `_get_clean_env()` (so the template's
  `VIRTUAL_ENV` doesn't break `uv run --project`); confirm `analyze` degrades
  gracefully (bag-only / ulog-only) and gives actionable errors when a run or
  skein is missing.
