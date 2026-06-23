# Plan 014: skein keeps a separate uv venv per environment (no host↔container thrash)

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. Touch only the files listed as in scope.
>
> **This plan targets the `ros-px4-template` repo**, NOT skein. See "Git
> workflow" for how to create the worktree — the dispatching session's cwd may
> be a different repo, so the worktree path and `-C` target are spelled out.
>
> **Drift check (run first)**:
> `git -C /home/ivy/Projects/ros-px4-template diff --stat 7c8cf86..HEAD -- tools/skein_analyze.py tasks.py tests/unit/test_skein_analyze.py docs/SKEIN.md`
> If any of those files changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P3
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none (builds on plans 009–013, all DONE/merged)
- **Category**: dx
- **Planned at**: commit `7c8cf86`, 2026-06-22

## Why this matters

`just analyze` runs skein as a separate uv project via
`uv run --project <skein_dir> skein …`. uv materializes that project's venv at
`<skein_dir>/.venv`, and a venv records exactly one interpreter. But the two
environments this command runs in have different Pythons:

- **host** (CachyOS): Python **3.14**, `python3` at `/usr/sbin/python3`
- **`ubuntu` distrobox** (where `just analyze` normally runs via the `_run`
  auto-enter): Python **3.12.3**, `python3` at `/usr/bin/python3`

Because both share the single `<skein_dir>/.venv`, every switch between host
and container makes uv tear down and rebuild that venv to match the current
interpreter. It is harmless and self-correcting, but it's slow, noisy, and
redundant work on every cross-environment invocation.

The fix: give each environment its own uv venv directory (selected
automatically), so neither clobbers the other. We do this by setting
`UV_PROJECT_ENVIRONMENT` (uv's documented override for the project venv path)
to a per-environment path when `just analyze` spawns skein. The default
`<skein_dir>/.venv` is left untouched for people running skein directly.

## Current state

Two files change; one test file is extended.

### `tools/skein_analyze.py` — builds the skein argv; resolves paths

The file's header and imports today (`tools/skein_analyze.py:1-18`):

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
```

The module is pure helpers (no side effects on import). `overlay_argv` and
`query_argv` build `["uv", "run", "--project", str(skein_dir), "skein", …]`.
This plan ADDS two new helpers; it does not change the existing ones.

### `tasks.py` — the `analyze` command runs the subprocess

`tasks.py:599-615` (the env is built once, then reused for overlay and query):

```python
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
```

`skein_analyze` is already imported at `tasks.py:161` (`import skein_analyze`).
`_get_clean_env()` returns a plain `dict[str, str]` copy of `os.environ` with
uv/venv entries stripped from `PATH` (`tasks.py:73-88`). Setting one more key on
that dict is the entire `tasks.py` change.

### `tests/unit/test_skein_analyze.py` — existing pure-function tests

Header / import pattern to match (`tests/unit/test_skein_analyze.py:1-15`):

```python
"""Unit tests for skein analyze helpers (no skein/ROS required)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

import pytest

import skein_analyze
```

Tests are plain `def test_*` functions asserting on return values; some use
`monkeypatch`. Match this exact style.

### Conventions to follow

- Ruff lints `src/core, tests, tools, sim, hardware` (from `tasks.py:392`,
  `def check`). So **`tools/skein_analyze.py` and
  `tests/unit/test_skein_analyze.py` ARE linted and formatted** — they must pass
  `ruff check` and `ruff format --check`. `tasks.py` is NOT in that list, so the
  one-line addition there is not lint-gated, but still write it cleanly.
- Ruff config (`pyproject.toml:29-37`): `target-version = py312`,
  `line-length = 100`, selects include `I` (import sorting) and `UP`
  (pyupgrade). New imports must be sorted; keep lines ≤100 cols.
- Type hints everywhere (the codebase uses `from __future__ import annotations`
  and `X | None` unions).

## Commands you will need

| Purpose          | Command                                                                                  | Expected on success            |
|------------------|------------------------------------------------------------------------------------------|--------------------------------|
| Install dev deps | `uv sync --group dev`                                                                     | exit 0 (fresh worktree needs this) |
| Lint (changed)   | `uv run ruff check tools/skein_analyze.py tests/unit/test_skein_analyze.py`               | exit 0, no errors              |
| Format check     | `uv run ruff format --check tools/skein_analyze.py tests/unit/test_skein_analyze.py`      | exit 0                         |
| Unit tests       | `uv run pytest tests/unit/test_skein_analyze.py -q`                                        | all pass                       |

Run all commands with the worktree as cwd (see Git workflow). Do **not** run
`just check` or the full `tests/unit/` suite: `tests/unit/test_scenario_verdict.py`
fails collection with `ModuleNotFoundError: No module named 'rclpy'` in this
ROS-free environment — that is a known pre-existing quirk, not your regression.
Scope the test command to the one file as shown.

## Scope

**In scope** (the only files you may modify):
- `tools/skein_analyze.py` — add the two helpers
- `tasks.py` — add exactly one line in `analyze` (set `UV_PROJECT_ENVIRONMENT`)
- `tests/unit/test_skein_analyze.py` — add tests for the new helpers
- `docs/SKEIN.md` — one bullet in the Configuration section
- `plans/README.md` — handled by your reviewer; do NOT edit it

**Out of scope** (do NOT touch):
- The existing functions in `skein_analyze.py` (`resolve_skein_dir`,
  `resolve_run_dir`, `find_bag_mcap`, `overlay_argv`, `query_argv`) — unchanged.
- `_get_clean_env` and any other part of `tasks.py` besides the single added
  line in `analyze`.
- `tools/bag_recorder.py`, `tools/ulog_retrieve.py`, the justfile — unrelated.
- skein itself (`../skein`) — this plan does not modify the skein repo at all.

## Git workflow

The dispatching session's cwd may not be this repo. Create the worktree
explicitly against the template repo:

```
git -C /home/ivy/Projects/ros-px4-template worktree add -b advisor/014-skein-venv \
    /home/ivy/.cache/advisor-worktrees/rpt-014 main
```

Then `cd /home/ivy/.cache/advisor-worktrees/rpt-014` and do all work there.

- Branch: `advisor/014-skein-venv`
- Commit style: conventional commits (see `git log --oneline`, e.g.
  `feat(analyze): just analyze runs skein overlay/query over a recorded run`).
  A single commit is fine, e.g.
  `fix(analyze): keep a per-environment skein venv to avoid host<->container rebuilds`.
- End the commit message body with:
  `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`
- Do NOT push, open a PR, or merge. Do NOT edit `plans/README.md`.

## Steps

### Step 1: Add the two helpers to `tools/skein_analyze.py`

Add `import re` to the imports (keep them sorted: `os`, `re`, then
`from pathlib import Path`). Add a module-level constant and two functions.
Place the new code after the `RUNS_DIR = ROOT / "logs" / "runs"` line and
before `class AnalyzeError`. Target shape:

```python
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUNS_DIR = ROOT / "logs" / "runs"

# distrobox/podman create this file inside a container; absent on the host.
_CONTAINERENV = Path("/run/.containerenv")


def _env_tag() -> str:
    """A short, filesystem-safe label for the current execution environment.

    skein is invoked via ``uv run --project <skein>``; its venv records ONE
    interpreter. The host and the ``ubuntu`` distrobox have different Pythons,
    so a shared venv is rebuilt on every host<->container switch. Tagging the
    venv per environment stops that. distrobox sets ``CONTAINER_ID`` (the
    container name) and creates ``/run/.containerenv``; on the host neither is
    present, so the tag is ``host``.
    """
    cid = os.environ.get("CONTAINER_ID", "").strip()
    if not cid and _CONTAINERENV.exists():
        cid = "container"
    return re.sub(r"[^A-Za-z0-9_.-]", "_", cid) or "host"


def skein_venv_dir(tag: str | None = None) -> Path:
    """Per-environment uv venv directory for skein, outside both repos.

    Used as ``UV_PROJECT_ENVIRONMENT`` when spawning skein so the host
    (e.g. Python 3.14) and the distrobox container (Python 3.12) keep separate
    venvs instead of rebuilding the shared ``<skein>/.venv`` on every switch.
    Lives under the user cache (honors ``XDG_CACHE_HOME``).
    """
    base = os.environ.get("XDG_CACHE_HOME", "").strip()
    root = Path(base) if base else Path.home() / ".cache"
    return root / "ros-px4-template" / "skein-venv" / (tag or _env_tag())
```

`_CONTAINERENV` is a module-level constant specifically so tests can monkeypatch
it deterministically regardless of where they run.

**Verify**: `uv run ruff check tools/skein_analyze.py` → exit 0, no errors.

### Step 2: Set `UV_PROJECT_ENVIRONMENT` in the `analyze` command

In `tasks.py`, in the `analyze` function, the line `env = _get_clean_env()`
(currently `tasks.py:599`) is immediately followed by adding one line:

```python
    env = _get_clean_env()
    env.setdefault("UV_PROJECT_ENVIRONMENT", str(skein_analyze.skein_venv_dir()))
```

Use `setdefault` so a user who has already exported `UV_PROJECT_ENVIRONMENT`
keeps their value. This is the ONLY change to `tasks.py`. The same `env` is
already passed to both the overlay and query subprocesses, so both are covered.

**Verify**: `git -C /home/ivy/.cache/advisor-worktrees/rpt-014 diff tasks.py`
shows exactly one added line (the `env.setdefault(...)` line) and nothing else.

### Step 3: Add tests for the new helpers

Append to `tests/unit/test_skein_analyze.py`, matching its existing style
(plain `def test_*`, `monkeypatch`). Cover:

- `_env_tag` returns the sanitized `CONTAINER_ID` when set
  (`monkeypatch.setenv("CONTAINER_ID", "ubuntu")` → `"ubuntu"`).
- `_env_tag` sanitizes unsafe characters
  (`CONTAINER_ID="a/b c"` → `"a_b_c"`).
- `_env_tag` returns `"host"` when `CONTAINER_ID` is unset/empty AND no
  containerenv marker: `monkeypatch.delenv("CONTAINER_ID", raising=False)` and
  `monkeypatch.setattr(skein_analyze, "_CONTAINERENV", tmp_path / "nope")`.
- `_env_tag` returns `"container"` when `CONTAINER_ID` is unset but the marker
  exists: delenv CONTAINER_ID, create a temp file, and
  `monkeypatch.setattr(skein_analyze, "_CONTAINERENV", that_file)`.
- `skein_venv_dir` honors `XDG_CACHE_HOME`:
  `monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))`, then
  `skein_venv_dir("ubuntu") == tmp_path / "ros-px4-template" / "skein-venv" / "ubuntu"`.
- `skein_venv_dir` falls back to `~/.cache` when `XDG_CACHE_HOME` is unset:
  `monkeypatch.delenv("XDG_CACHE_HOME", raising=False)` and
  `monkeypatch.setattr(skein_analyze.Path, "home", lambda: tmp_path)`, then
  `skein_venv_dir("host") == tmp_path / ".cache" / "ros-px4-template" / "skein-venv" / "host"`.
  (Note: `skein_analyze` imports `Path` from `pathlib`, so patch
  `skein_analyze.Path.home`.)
- `skein_venv_dir(None)` uses `_env_tag` (set `CONTAINER_ID=ubuntu`, assert the
  final path component is `ubuntu`).

**Verify**: `uv run pytest tests/unit/test_skein_analyze.py -q` → all pass
(existing tests + your new ones).

### Step 4: Document it in `docs/SKEIN.md`

In the `## Configuration` section, after the existing `SKEIN_DIR` bullet, add
one bullet. Keep the prose tight and factual:

```markdown
- `UV_PROJECT_ENVIRONMENT` — where skein's uv venv lives. By default `just
  analyze` picks a per-environment path under your cache
  (`~/.cache/ros-px4-template/skein-venv/<env>`, keyed on host vs. the distrobox
  container) so the host (e.g. Python 3.14) and the container (Python 3.12)
  don't rebuild a shared `<skein>/.venv` on every switch. Export it yourself to
  override.
```

**Verify**: `grep -n UV_PROJECT_ENVIRONMENT docs/SKEIN.md` → at least one match
in the Configuration section.

## Test plan

- New tests in `tests/unit/test_skein_analyze.py`, modeled on the existing
  `def test_*` + `monkeypatch` functions in that file.
- Cases: the seven listed in Step 3 (CONTAINER_ID happy path, sanitization,
  host fallback, containerenv marker, XDG honored, ~/.cache fallback, tag=None
  delegates to `_env_tag`).
- Verification: `uv run pytest tests/unit/test_skein_analyze.py -q` → all pass,
  including the new tests.

## Done criteria

Machine-checkable. ALL must hold (run from the worktree):

- [ ] `uv run ruff check tools/skein_analyze.py tests/unit/test_skein_analyze.py` exits 0
- [ ] `uv run ruff format --check tools/skein_analyze.py tests/unit/test_skein_analyze.py` exits 0
- [ ] `uv run pytest tests/unit/test_skein_analyze.py -q` exits 0; the new tests exist and pass
- [ ] `grep -n "UV_PROJECT_ENVIRONMENT" tasks.py` returns exactly one line (the `env.setdefault` line)
- [ ] `grep -n "skein_venv_dir\|_env_tag" tools/skein_analyze.py` shows both helpers defined
- [ ] `grep -n "UV_PROJECT_ENVIRONMENT" docs/SKEIN.md` returns a match
- [ ] `git -C <worktree> diff --stat` shows only these 4 files changed:
      `tools/skein_analyze.py`, `tasks.py`, `tests/unit/test_skein_analyze.py`,
      `docs/SKEIN.md` (NOT `plans/README.md`)

## STOP conditions

Stop and report back (do not improvise) if:

- The drift check shows any in-scope file changed since `7c8cf86` and the live
  code no longer matches the "Current state" excerpts.
- `analyze` in `tasks.py` no longer has the `env = _get_clean_env()` line shown
  in Current state (someone refactored it).
- `uv sync --group dev` or any verification command fails twice after a
  reasonable fix attempt.
- The fix appears to require touching a file outside the in-scope list.

## Maintenance notes

For whoever owns this next:

- This only affects how `just analyze` spawns skein. Running skein directly
  (`uv run --project ../skein skein …` from a shell) still uses
  `<skein>/.venv` and is unaffected by design.
- If a third environment is added (e.g. a second distrobox), it gets its own
  venv automatically via `CONTAINER_ID`. No code change needed.
- The per-environment venvs accumulate under
  `~/.cache/ros-px4-template/skein-venv/`. They're disposable; deleting them
  just forces one rebuild. Not wired into `just clean` (which only touches the
  template's own `logs/`), and intentionally so — they're shared across runs.
- Reviewer should confirm the `tasks.py` diff is genuinely one line and that the
  new tests assert on concrete return values (not no-op asserts).
