# Plan 039: Cache the workspace env sourcing that runs on every `just` command

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report - do not improvise. When done, update the status row for this plan
> in `plans/README.md` - unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat ead4cc6..HEAD -- tasks.py`
> If `tasks.py` changed, confirm `_source_workspace_env` still matches the
> excerpt below; on a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P3
- **Effort**: S
- **Risk**: MED (env drift if invalidation is wrong; mitigated by mtime keys and a fallback path)
- **Depends on**: none
- **Category**: perf
- **Planned at**: commit `ead4cc6`, 2026-07-06

## Why this matters

`tasks.py` runs `_source_workspace_env()` at module import, i.e. on EVERY
`just` invocation - including pure-CPU ones like `just mission list`,
`just cap show`, `just log summary`. It spawns `bash -c "source
install/setup.bash && python3 -c ...json.dumps(dict(os.environ))"`, which
itself chains ROS's setup scripts: roughly 100-300 ms of subprocess overhead
per command, paid dozens of times per agent debugging session. The sourced
environment only changes when the workspace is rebuilt, so it caches
perfectly on the setup file's mtime.

## Current state

`tasks.py:55-70` (runs at import, line 70):

```python
def _source_workspace_env() -> None:
    ws_setup = ROOT / "install" / "setup.bash"
    if ws_setup.exists():
        try:
            cmd = f"source {ws_setup} && python3 -c 'import os, json; print(json.dumps(dict(os.environ)))'"
            res = subprocess.run(
                ["bash", "-c", cmd], capture_output=True, text=True, check=True, cwd=str(ROOT)
            )
            new_env = json.loads(res.stdout.strip())
            for k, v in new_env.items():
                os.environ[k] = v
        except Exception as e:
            print(f"Warning: failed to source workspace env: {e}", file=sys.stderr)


_source_workspace_env()
```

Facts that shape the design:

- `install/setup.bash` chains `local_setup.bash` files and the ROS underlay
  named by `ROS_SETUP` (default `/opt/ros/jazzy/setup.bash`, see
  `_ros_setup_path()` around `tasks.py:91`).
- `just clean` removes `install/` (and `build/`), so a cache stored INSIDE
  `install/` is invalidated by clean for free.
- `_load_dotenv()` runs before this and seeds `os.environ`; the sourced env
  captures the full bash-side environment, so the cache must snapshot exactly
  what the subprocess prints, not a delta.
- `tasks.py` is NOT covered by `just check` lint/typecheck; verify with
  `uv run ruff check tasks.py` and by running commands directly (repo
  convention, see `plans/README.md` round-2 notes).

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Lint | `uv run ruff check tasks.py` | exit 0 |
| Timing before/after | `time just mission list` (run twice, compare) | warm run visibly faster |
| Behavior check | `just cap show`, `just log summary`, `just --list` | unchanged output |
| Full gate | `just check` | exit 0 |

## Scope

**In scope**:
- `tasks.py` (`_source_workspace_env` only)

**Out of scope**:
- `_load_dotenv`, `_get_clean_env`, `_ros_launch_env` - unchanged.
- Gating which commands source the env at all (rejected approach: fragile
  allowlist; every ROS-touching command would need tagging).
- Adding a new dependency; stdlib only.

## Git workflow

- Branch: `advisor/039-cache-env-sourcing`
- Commit style: `perf(tasks): cache sourced workspace env keyed on setup.bash mtime`
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Rewrite `_source_workspace_env` with a cache

Replace the function body (keep the name and zero-arg signature; line 70's
import-time call stays):

Design:

1. `ws_setup = ROOT / "install" / "setup.bash"`; if missing, return (as now).
2. Cache file: `ROOT / "install" / ".ws_env_cache.json"`. Living inside
   `install/` means `just clean` wipes it and it can never exist without the
   workspace it caches.
3. Cache key (stored inside the JSON under `"_key"`): a dict of
   `{"setup_mtime_ns": ws_setup.stat().st_mtime_ns, "ros_setup": _ros_setup_path(), "ros_setup_mtime_ns": <mtime_ns of that file, or 0 if missing>}`.
   Note `_ros_setup_path()` is defined AFTER this function runs at import -
   inline the same expression instead:
   `os.environ.get("ROS_SETUP", "/opt/ros/jazzy/setup.bash")`.
4. Read path: if the cache file parses as JSON and its `"_key"` equals the
   freshly computed key, apply `env = data["env"]` to `os.environ` (same
   `for k, v ...: os.environ[k] = v` loop) and return.
5. Miss path: run the existing `bash -c source ...` subprocess exactly as
   today, apply the env, then best-effort write
   `{"_key": key, "env": new_env}` to the cache file (wrap the write in its
   own `try/except Exception: pass` - a read-only FS must not break commands).
6. Keep the existing outer `except Exception` warning behavior for the
   subprocess path. A corrupt/unreadable cache file must fall through to the
   miss path, never raise.

Keep the function short and comment only the non-obvious constraint (cache
lives in `install/` so `just clean` invalidates it).

**Verify**: `uv run ruff check tasks.py` -> exit 0

### Step 2: Behavior and invalidation checks (no sim needed)

Run from a shell where `install/setup.bash` exists (distrobox if needed):

1. `rm -f install/.ws_env_cache.json && time just mission list` -> works,
   creates `install/.ws_env_cache.json` (check with `ls`).
2. `time just mission list` again -> same output, measurably faster (the
   bash subprocess is skipped; expect roughly 100-300 ms less).
3. Invalidation: `touch install/setup.bash && just mission list` -> still
   works; confirm the cache file's mtime changed (it was rewritten).
4. Corruption: `echo garbage > install/.ws_env_cache.json && just mission list`
   -> works (falls through to sourcing), cache file is valid JSON afterwards.
5. Sanity across command families: `just cap show`, `just log summary`,
   `just status` -> normal output/verdicts (status may report NOT READY with
   no stack up; that is its correct behavior).

**Verify**: all five checks behave as listed.

### Step 3: Full gate

**Verify**: `just check` -> exit 0. Note `just check` includes a build; run a
`just mission list` after it to confirm the rebuilt `install/` still
cache-hits correctly (the build may update `setup.bash`'s mtime - a miss then
a fresh cache is the expected sequence, not an error).

## Test plan

`tasks.py` is outside the unit-test/lint gate by repo convention; Step 2's
five direct-command checks are the test plan (create, hit, invalidate,
corrupt-recover, cross-command sanity). No new unit tests.

## Done criteria

- [ ] `rg -n "ws_env_cache" tasks.py` -> cache path referenced in `_source_workspace_env` only
- [ ] Step 2 checks 1-5 all behave as listed
- [ ] `uv run ruff check tasks.py` -> exit 0
- [ ] `just check` exits 0
- [ ] `git status` shows only `tasks.py` modified (plus the untracked cache file under `install/`, which is gitignored territory - confirm `git status` does NOT list it; if it does, STOP)
- [ ] `plans/README.md` status row updated

## STOP conditions

- `git status` shows `install/.ws_env_cache.json` as trackable (install/ not
  ignored) - do not commit it; report.
- The warm run is NOT faster (cache never hits) - report timings instead of
  adding more keys.
- Any command from Step 2.5 changes behavior/output vs main - env drift;
  report which env var differs (`diff <(sorted env dump)` from both paths).

## Maintenance notes

- If a future overlay adds a second setup file to the chain, add its mtime to
  the key - the key dict shape makes that a one-line change.
- Reviewer: the miss path must remain byte-identical to today's subprocess
  call; the cache is an optimization wrapper, not a reimplementation.
