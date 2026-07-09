# Plan 029: Batch topic queries in `tools/check_topics.py` (PERF-03)

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat ead4cc6..HEAD -- tools/check_topics.py tests/unit/test_check_topics.py`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: perf
- **Planned at**: commit `ead4cc6`, 2026-06-29

## Why this matters

Currently, `tools/check_topics.py` executes `ros2 topic info <topic>` in a loop for every topic defined in the manifest (`docs/TOPICS.md`). For a standard configuration with 12–14 topics, this incurs O(N) subprocess spawns of the `ros2` CLI. Since each ROS 2 CLI invocation initializes Python, sources graph metadata, and contacts the DDS discovery daemon, each call takes ~0.4–0.5 seconds, totaling 5–7 seconds per audit.

By batching this query into a single call to `ros2 topic list --verbose` and parsing the consolidated output in Python, we reduce the subprocess overhead to O(1). This speeds up the topic graph audit to under 0.5 seconds, drastically improving the feedback loop of `just check`, E2E tests, and live validations.

## Current state

In `tools/check_topics.py:71-86`:
```python
def _live_topic_info(topic: str) -> tuple[str | None, int, int]:
    """(msg_type, publisher_count, subscription_count) from `ros2 topic info`."""
    result = subprocess.run(["ros2", "topic", "info", topic], capture_output=True, text=True)
    if result.returncode != 0:
        return None, 0, 0
    msg_type: str | None = None
    pub = sub = 0
    for raw in result.stdout.splitlines():
        ln = raw.strip()
        if ln.startswith("Type:"):
            msg_type = ln.split(":", 1)[1].strip()
        elif ln.startswith("Publisher count:"):
            pub = int(ln.split(":", 1)[1].strip() or 0)
        elif ln.startswith("Subscription count:"):
            sub = int(ln.split(":", 1)[1].strip() or 0)
    return msg_type, pub, sub
```

And in `tools/check_topics.py:149-160` (inside the `main` function):
```python
    for spec in specs:
        if not should_enforce(spec, vision):
            typer.echo(f"  [SKIP] {spec.name} (vision off)")
            continue
        checked_count += 1
        observed_type, pub, sub = _live_topic_info(spec.name)
        problems = check_spec(spec, observed_type, pub, sub)
        if problems:
            failed_count += 1
            typer.echo(f"  [FAIL] {spec.name}: {'; '.join(problems)}")
```

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Unit tests (primary gate) | `uv run pytest tests/unit/test_check_topics.py -q` | all pass incl. new mocked cases |
| Dry-run still works | `uv run python tools/check_topics.py --manifest docs/TOPICS.md --dry-run` | lists topics, exit 0 |
| Quality gate | `just check` | exits 0 |
| Live confirmation (needs sim) | `just sim` then `just log topics` | all topics checked in < 0.5s, exit 0 |

## Scope

**In scope**:
- `tools/check_topics.py` (replace single-topic `_live_topic_info` with a batched `_query_live_topics` runner & parser, update `main()` lookup)
- `tests/unit/test_check_topics.py` (add unit tests that mock the output of `ros2 topic list --verbose` and assert correct dictionary parsing)

**Out of scope**:
- Changing the manifest `docs/TOPICS.md` or adding/removing topics.
- Changing `check_spec` logic or `TopicSpec` schema.
- Changing `tasks.py` invocation details (which already calls `check_topics.py` correctly).

## Git workflow

- Branch: `perf/029-batch-topic-queries`
- Commit style: conventional commits. Suggested message:
  `perf(check-topics): batch topic queries via single ros2 topic list --verbose`.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Implement `_query_live_topics` parser

Remove `_live_topic_info(topic)` and add `_query_live_topics()` which runs `ros2 topic list --verbose` once. It should parse the output format and return a dictionary of topic name mapping to `(msg_type, publisher_count, subscriber_count)`.

The parser should search for sections `Published topics:` and `Subscribed topics:`, identifying topic definition lines starting with `*` and extracting names, types, and counts using a regular expression:

```python
def _query_live_topics() -> dict[str, tuple[str | None, int, int]]:
    """Run `ros2 topic list --verbose` once and return a dict mapping
    topic name to (msg_type, publisher_count, subscriber_count).
    """
    result = subprocess.run(["ros2", "topic", "list", "--verbose"], capture_output=True, text=True)
    if result.returncode != 0:
        return {}

    topics_info: dict[str, list] = {}
    current_section = None  # "pub" | "sub"
    pattern = re.compile(r"^\*\s+(\S+)\s+\[([^\]]+)\]\s+(\d+)\s+(?:publisher|subscriber)s?$")

    for line in result.stdout.splitlines():
        ln = line.strip()
        if not ln:
            continue
        if ln.startswith("Published topics:"):
            current_section = "pub"
            continue
        elif ln.startswith("Subscribed topics:"):
            current_section = "sub"
            continue

        if ln.startswith("*"):
            match = pattern.match(ln)
            if match:
                name = match.group(1)
                msg_type = match.group(2)
                count = int(match.group(3))

                if name not in topics_info:
                    topics_info[name] = [msg_type, 0, 0]

                if current_section == "pub":
                    topics_info[name][1] = count
                elif current_section == "sub":
                    topics_info[name][2] = count

    return {name: (val[0], val[1], val[2]) for name, val in topics_info.items()}
```

**Verify**: `uv run python -c "import sys; sys.path.insert(0,'tools'); import check_topics"` exits 0.

### Step 2: Update the `main()` loop to query live topics in batch

In `tools/check_topics.py`'s `main()` function, query all live topics before entering the specs loop:

```python
    specs = parse_manifest(text)
    failed_count = 0
    checked_count = 0

    # Query all live topics in a single O(1) subprocess call
    live_topics = _query_live_topics()

    for spec in specs:
        if not should_enforce(spec, vision):
            typer.echo(f"  [SKIP] {spec.name} (vision off)")
            continue
        checked_count += 1
        observed_type, pub, sub = live_topics.get(spec.name, (None, 0, 0))
        problems = check_spec(spec, observed_type, pub, sub)
        if problems:
            failed_count += 1
            typer.echo(f"  [FAIL] {spec.name}: {'; '.join(problems)}")
        else:
            typer.echo(f"  [OK] {spec.name}")
```

**Verify**: `uv run python tools/check_topics.py --manifest docs/TOPICS.md --dry-run` still runs and exits 0 (dry-run unaffected).

### Step 3: Add unit tests for the parser

In `tests/unit/test_check_topics.py`, add unit tests mocking the subprocess run of `ros2 topic list --verbose`:

```python
from unittest.mock import patch, MagicMock
from check_topics import _query_live_topics

def test_query_live_topics_parsing() -> None:
    mock_stdout = """
Published topics:
 * /drone/odom [nav_msgs/msg/Odometry] 1 publisher
 * /clock [rosgraph_msgs/msg/Clock] 2 publishers

Subscribed topics:
 * /drone/odom [nav_msgs/msg/Odometry] 1 subscriber
 * /fmu/in/trajectory_setpoint [px4_msgs/msg/TrajectorySetpoint] 1 subscriber
"""
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = mock_stdout

    with patch("subprocess.run", return_value=mock_result) as mock_run:
        info = _query_live_topics()
        mock_run.assert_called_once_with(["ros2", "topic", "list", "--verbose"], capture_output=True, text=True)

        assert "/drone/odom" in info
        assert info["/drone/odom"] == ("nav_msgs/msg/Odometry", 1, 1)

        assert "/clock" in info
        assert info["/clock"] == ("rosgraph_msgs/msg/Clock", 2, 0)

        assert "/fmu/in/trajectory_setpoint" in info
        assert info["/fmu/in/trajectory_setpoint"] == ("px4_msgs/msg/TrajectorySetpoint", 0, 1)

        assert "/missing/topic" not in info


def test_query_live_topics_handles_subprocess_failure() -> None:
    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_result.stdout = ""

    with patch("subprocess.run", return_value=mock_result):
        info = _query_live_topics()
        assert info == {}
```

**Verify**: `uv run pytest tests/unit/test_check_topics.py -q` passes all tests.

### Step 4: Quality Gate Verification

**Verify**: `just check` exits 0.

### Step 5: Live Confirmation (needs sim)

1. Start the simulation:
   ```bash
   just sim
   ```
2. Run the topics check and observe execution speed:
   ```bash
   just log topics
   ```
   *Expected*: The check prints the status of all topics and exits 0 in less than 0.5 seconds.
3. Stop the simulation:
   ```bash
   just stop
   ```

If you do not have a running sim environment, report Step 5 as "pending operator live confirmation".

## Test plan

- **Unit tests**: The new test cases in `tests/unit/test_check_topics.py` mock stdout of `ros2 topic list --verbose` to guarantee parser robustness without needing a live ROS graph.
- **Dry-run validation**: Running `check_topics.py --dry-run` ensures the manifest parser and source search are fully intact.
- **Execution time compare**: Confirm that the total execution time of `just log topics` drops significantly (e.g. from 5s+ to < 0.5s).

## Done criteria

- [ ] `_live_topic_info` is removed from `tools/check_topics.py`
- [ ] `_query_live_topics` is implemented and parses `ros2 topic list --verbose` stdout correctly
- [ ] The specs loop in `main()` calls `_query_live_topics` exactly once
- [ ] Two new parser unit tests are added to `tests/unit/test_check_topics.py`
- [ ] `uv run pytest tests/unit/test_check_topics.py -q` passes successfully
- [ ] `just check` completes with exit code 0
- [ ] No files modified outside of `tools/check_topics.py` and `tests/unit/test_check_topics.py`
- [ ] Plan status row in `plans/README.md` is updated (or marked ready for review)

## STOP conditions

Stop and report back if:
- `ros2 topic list --verbose` is not supported or returns a different format on the platform than the expected format.
- The unit tests pass locally but fail in containerized environments due to missing Python libraries.
