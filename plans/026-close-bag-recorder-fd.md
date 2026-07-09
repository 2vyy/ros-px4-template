# Plan 026: Close Parent File Descriptor in Bag Recorder (CORRECTNESS-02)

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving on. If
> anything in "STOP conditions" occurs, stop and report. When done, update this
> plan's row in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat ead4cc6..HEAD -- tools/bag_recorder.py`
> If it changed, compare the "Current state" excerpt to the live code before
> proceeding; on a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: correctness
- **Planned at**: commit `ead4cc6`, 2026-06-29

## Why this matters

The `bag_recorder` module runs `ros2 bag record` to capture simulator data, redirecting output to `bag_record.log`. To do this, it opens a file handle (`log_fh`) in the parent process and passes it as `stdout`/`stderr` to `subprocess.Popen`. However, the parent process never closes its own file descriptor copy after the child process inherits it, resulting in a leaked file descriptor for each simulation run. Closing the file descriptor in the parent process releases the resource in the parent without affecting the child's copy.

## Current state

`tools/bag_recorder.py:81-108`:
```python
def start(
    run_dir: Path,
    env: dict[str, str],
    *,
    topics: list[str] | None = None,
    spawn=subprocess.Popen,
) -> subprocess.Popen[bytes] | None:
    """Spawn the detached recorder into its own setsid group; record its pid in
    logs/bag.pid. Best-effort: returns None and prints a warning on failure
    (never raises, so a missing mcap storage plugin can't abort the sim)."""
    topics = topics or _BAG_TOPICS
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_fh = (run_dir / "bag_record.log").open("w", encoding="utf-8")
    try:
        proc = spawn(
            _record_argv(run_dir, topics),
            env=env,
            stdout=log_fh,
            stderr=subprocess.STDOUT,
            preexec_fn=os.setsid,
            cwd=str(ROOT),
        )
    except Exception as e:
        print(f"Warning: bag recorder failed to start: {e}", file=sys.stderr)
        return None
    BAG_PIDFILE.write_text(str(proc.pid))
    return proc
```
The file handle `log_fh` is opened, but `log_fh.close()` is never called in the parent process, leaving the file descriptor open in the parent.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Run bag recorder tests | `uv run pytest tests/unit/test_bag_recorder.py -q` | all pass |
| Full unit suite | `uv run pytest tests/unit/ -q` | all pass |
| Lint | `uv run ruff check tools/bag_recorder.py tests/unit/test_bag_recorder.py` | exit 0 |
| Typecheck | `uv run ty check tools/ tests/unit/` | exit 0 |

## Scope

**In scope**:
- `tools/bag_recorder.py` (modify) — Close `log_fh` in the parent process after spawning.
- `tests/unit/test_bag_recorder.py` (modify) — Add a test case asserting the parent file descriptor is closed when `start` returns.

**Out of scope**:
- Modifying how logging is configured for the ros2 bag process.
- Modifying other components of `bag_recorder.py` (e.g., `stop()`).

## Steps

### Step 1: Close File Descriptor in `start`

Modify `start` in `tools/bag_recorder.py` to ensure `log_fh` is closed in the parent process using a `finally` block, which handles both successful spawns and failures correctly.

Modify `tools/bag_recorder.py:81-108`:
```python
def start(
    run_dir: Path,
    env: dict[str, str],
    *,
    topics: list[str] | None = None,
    spawn=subprocess.Popen,
) -> subprocess.Popen[bytes] | None:
    """Spawn the detached recorder into its own setsid group; record its pid in
    logs/bag.pid. Best-effort: returns None and prints a warning on failure
    (never raises, so a missing mcap storage plugin can't abort the sim)."""
    topics = topics or _BAG_TOPICS
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_fh = (run_dir / "bag_record.log").open("w", encoding="utf-8")
    try:
        proc = spawn(
            _record_argv(run_dir, topics),
            env=env,
            stdout=log_fh,
            stderr=subprocess.STDOUT,
            preexec_fn=os.setsid,
            cwd=str(ROOT),
        )
        BAG_PIDFILE.write_text(str(proc.pid))
        return proc
    except Exception as e:
        print(f"Warning: bag recorder failed to start: {e}", file=sys.stderr)
        return None
    finally:
        log_fh.close()
```

**Verify**: `uv run ruff check tools/bag_recorder.py` → exit 0.

### Step 2: Add Unit Test for Resource Leakage

Add a unit test `test_start_closes_log_file_handle_in_parent` to `tests/unit/test_bag_recorder.py` to verify that the file handle opened for the log is closed in the parent process upon return of the `start` function.

Add the following function to `tests/unit/test_bag_recorder.py`:
```python
def test_start_closes_log_file_handle_in_parent(monkeypatch, tmp_path) -> None:
    pidfile = tmp_path / "bag.pid"
    monkeypatch.setattr(bag_recorder, "BAG_PIDFILE", pidfile)
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    opened_file_handles = []
    original_open = Path.open

    def wrapped_open(self, *args, **kwargs):
        fh = original_open(self, *args, **kwargs)
        if self.name == "bag_record.log":
            opened_file_handles.append(fh)
        return fh

    monkeypatch.setattr(Path, "open", wrapped_open)

    class FakeProc:
        pid = 4242

    def fake_spawn(argv, **kwargs):
        return FakeProc()

    proc = bag_recorder.start(run_dir, {"PATH": "/usr/bin"}, spawn=fake_spawn)

    assert proc is not None
    assert len(opened_file_handles) == 1
    assert opened_file_handles[0].closed is True
```

**Verify**: `uv run pytest tests/unit/test_bag_recorder.py -q` → all pass.

### Step 3: Run Full Validation

Run linting, typechecking, and the full test suite to guarantee there are no regressions.

```bash
uv run pytest tests/unit/ -q
uv run ruff check tools/bag_recorder.py tests/unit/test_bag_recorder.py
uv run ty check tools/ tests/unit/
```

## Test plan

- Test coverage in `tests/unit/test_bag_recorder.py` verifying file handle closures and spawn success/failure resilience.
- Verify through local run of the unit tests: `uv run pytest tests/unit/` -> all pass.

## Done criteria

- [ ] `tools/bag_recorder.py` closes the opened log file handle `log_fh` in the parent process.
- [ ] Test `test_start_closes_log_file_handle_in_parent` added to `tests/unit/test_bag_recorder.py` and passes.
- [ ] `uv run pytest tests/unit/` exits with 0.
- [ ] `uv run ruff check` and `uv run ty check` exit with 0.

## STOP conditions

- If `tools/bag_recorder.py` has drifted from the expected current state snippet.
- If the subprocess is no longer able to write its output to `bag_record.log` in real simulator boots (indicating that child file descriptor inheritance was disrupted, though the standard OS behavior of `fork`/`exec` guarantees it remains open in the child).
