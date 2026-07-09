# Plan 036: Characterization tests for `tools/preflight.py` (the gate before every launch)

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report - do not improvise. When done, update the status row for this plan
> in `plans/README.md` - unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat ead4cc6..HEAD -- tools/preflight.py`
> If it changed, compare the "Current state" excerpts before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW (test-only; production file untouched)
- **Depends on**: none
- **Category**: tests
- **Planned at**: commit `ead4cc6`, 2026-07-06

## Why this matters

`tools/preflight.py` is the precondition gate invoked before `just sim`,
`just hw`, and `just test e2e` (tasks.py lines 489, 639, 815). A false pass
launches into a broken stack and the agent debugs a phantom sim failure; a
false fail blocks all runs. It currently has zero tests. This plan pins its
observable behavior with characterization tests - no production changes.

## Current state

- `tools/preflight.py` - the gate. Helpers worth pinning:
  - `_check(label, ok, detail, always_show_detail)` (lines 27-32): prints
    `[OK]  ` / `[FAIL]` lines; shows detail on failure or when forced;
    returns `ok`.
  - `_port_free(port)` (lines 35-40): True when nothing accepts a TCP
    connection on 127.0.0.1:port.
  - `_git_branch(path)` (lines 64-71): `git rev-parse --abbrev-ref HEAD`,
    returns `"<unknown>"` on nonzero exit.
  - `main()` (lines 74-211): argparse `--mode` (default `gui`); modes
    `px4`/`edit` skip port checks; mode `hw` adds MicroXRCEAgent + serial
    device checks; prints `Preflight OK.` / `Preflight FAILED ...`; exits
    0/1 via `sys.exit`.
- Tests import tools modules flat: `tests/conftest.py` inserts `tools/` into
  `sys.path`. See `tests/unit/test_wait_ready.py` for the import + mock
  pattern (it does `from wait_ready import app` and patches module attributes
  with `unittest.mock.patch`).

Excerpt (`tools/preflight.py:35-40`):

```python
def _port_free(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            return False  # something is listening
    except OSError:
        return True
```

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| New tests | `uv run pytest tests/unit/test_preflight.py -q` | all pass |
| Whole suite | `uv run pytest tests/unit -q` | pass (a pre-existing rclpy collection error in `test_scenario_verdict.py` may appear on non-ROS hosts) |
| Lint | `uv run ruff check tests/unit/test_preflight.py` | exit 0 |
| Full gate | `just check` | exit 0 |

## Scope

**In scope**:
- `tests/unit/test_preflight.py` (create)

**Out of scope**:
- `tools/preflight.py` itself - characterization only. If a test reveals a
  real bug, record it in your report; do not fix it here.
- `tools/wait_ready.py`, `tools/gcs_heartbeat.py` (gcs_heartbeat is plan 037).

## Git workflow

- Branch: `advisor/036-preflight-tests`
- Commit style: `test(preflight): characterization tests for the launch gate`
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Create `tests/unit/test_preflight.py`

Import as the other tools tests do (`import preflight` or
`from preflight import _check, _port_free, _git_branch, main`). Tests:

1. `test_port_free_on_unused_port`: bind a listener socket to port 0, read the
   assigned port, close it, then assert `_port_free(port)` is True.
2. `test_port_busy_detected`: keep a `socket` listening
   (`sock.bind(("127.0.0.1", 0)); sock.listen(1)`) and assert
   `_port_free(port)` is False while it is open.
3. `test_check_prints_fail_with_detail(capsys)`: `_check("x", False, "why")`
   returns False and captured output contains `[FAIL]` and `why`.
4. `test_check_hides_detail_on_ok(capsys)`: `_check("x", True, "why")` returns
   True and output does NOT contain `why` (no `always_show_detail`).
5. `test_git_branch_unknown_outside_repo(tmp_path)`:
   `_git_branch(tmp_path)` == `"<unknown>"`.
6. `test_main_fails_with_empty_env(monkeypatch, capsys)`: monkeypatch
   `ROS_SETUP`/`PX4_DIR` to `""` (via `monkeypatch.delenv`/`setenv`),
   monkeypatch `sys.argv` to `["preflight", "--mode", "px4"]` (px4 mode skips
   port checks so the test never touches real ports), call `preflight.main()`
   inside `pytest.raises(SystemExit)` and assert `e.value.code == 1` and
   output contains `Preflight FAILED`. Note: `main()` still runs the
   `uv run python -c "import pymavlink"` subprocess (uv is on PATH in dev
   envs); to keep the test hermetic and fast, also monkeypatch
   `preflight.shutil.which` to return None for `"uv"` (then the pymavlink
   check short-circuits to False, which is fine for a FAILED expectation).

**Verify**: `uv run pytest tests/unit/test_preflight.py -q` -> 6 passed

### Step 2: Whole-suite + gate

**Verify**: `uv run pytest tests/unit -q` -> no new failures;
`just check` -> exit 0

## Test plan

The six tests above ARE the deliverable: port probing both ways, `_check`
formatting contract (the `[OK]`/`[FAIL]` strings agents and humans read),
branch fallback, and the end-to-end FAILED exit path with hermetic env.
Pattern file: `tests/unit/test_wait_ready.py`.

## Done criteria

- [ ] `uv run pytest tests/unit/test_preflight.py -q` -> 6 passed
- [ ] `git diff --stat` shows `tools/preflight.py` unchanged
- [ ] `just check` exits 0
- [ ] `plans/README.md` status row updated

## STOP conditions

- `tools/preflight.py` helper signatures differ from the excerpts (drift).
- A test can only pass by modifying `tools/preflight.py` (report the bug
  instead - characterization must not change production behavior).
- Sandboxed environments may block even loopback socket listeners; if tests
  1-2 cannot bind sockets at all, mark them with
  `pytest.mark.skipif` on an explicit env probe and say so in your report.

## Maintenance notes

- When preflight gains checks (e.g. plan 043's world assets or hardware
  bring-up), extend this file - one test per check, same pattern.
- Reviewer: confirm test 6 does not depend on the developer's real `.env`
  (monkeypatch must cover both env vars).
