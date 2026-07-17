# Plan 068: CLI hygiene — preflight really checks UDP 8888, dead `--speed` plumbing removed, verdict papercuts fixed

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in "STOP conditions" occurs, stop and report — do not
> improvise. When done, update this plan's row in `plans/README.md` unless a
> reviewer told you they maintain the index.
>
> **Drift check (run first)**:
> `git diff --stat 6ce9aec..HEAD -- tools/preflight.py tools/e2e_status.py tools/status.py tasks.py justfile tests/unit/test_preflight.py tests/unit/test_e2e_status.py`
> On any mismatch with the "Current state" excerpts below, STOP.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none (068 and 067 both edit `tasks.py` in disjoint regions; land sequentially to avoid merge noise)
- **Category**: bug / tech-debt / dx
- **Planned at**: commit `6ce9aec`, 2026-07-16

## Why this matters

Four small, independently verified defects that each cost an agent a wasted
round-trip:

1. Preflight's "Port 8888 (MicroXRCEAgent) free" check does a **TCP** connect,
   but the agent listens on **UDP** — the check can never detect an occupied
   port, and its diagnostic never fires.
2. Preflight's failure remedy says `run: just sim-stop` — a recipe that does
   not exist (it's `just stop`). The dead name also appears in a `tasks.py`
   comment.
3. Plan 065 was rejected (any live `set_physics` corrupts PX4's estimator),
   but the e2e worker still carries a no-op `--speed` option, a `speed` state
   key, and an `e2e-status` display branch that can print "at 2.0x" while
   doing nothing. The option is unreachable (the spawner never passes it) and
   invites reintroduction of a known-dangerous concept.
4. Verdict-contract papercuts: `just status` docstrings promise JSON but the
   output is English; `just analyze`'s success path ends with no verdict line
   (AGENTS.md: "Every command ends in a concise English verdict").

## Current state

- `tools/preflight.py`:
  - `_port_free` (lines 35–40): `socket.create_connection(("127.0.0.1", port),
    timeout=0.5)` — TCP only. A UDP listener refuses the TCP connect →
    `OSError` → returns `True` ("free") always.
  - `_port_pid` (lines 43–61): runs `ss -lnp sport = :{port}` and IGNORES its
    `proto` parameter (TCP-only listing by default).
  - Lines 117–124: `port_8888_free = _port_free(8888)` … message
    `f"already in use {pid_8888} — run: just sim-stop"`. Line ~132: same
    `just sim-stop` text for port 9090. The launch starts the agent as UDP:
    `sim/launch/sim_full.launch.py:189` → `MicroXRCEAgent udp4 -p 8888`.
  - Port 9090 (rosbridge) genuinely IS TCP — its `_port_free` use is correct.
- `justfile:44` — the teardown recipe is named `stop`. `rg sim-stop justfile`
  → no matches.
- `tasks.py`:
  - Line 679 comment: `# port fails here with an accurate "run: just
    sim-stop" message.` (doubly stale: the message is inaccurate).
  - `_e2e_run(configs: list[dict], speed: float = 1.0)` (line 312); line 334
    stores `"speed": speed` in the state dict; line ~1139 seeds `"speed": 1.0`
    in the detach state; `e2e_worker` (lines 1171–1177) has
    `speed: float = typer.Option(1.0, "--speed", help="Physics speed
    factor.")` and calls `_e2e_run(configs, speed=speed)`. The only spawner
    (line ~1156) is `["uv", "run", "python", "tasks.py", "e2e-worker"]` — no
    `--speed`; the option is unreachable.
  - `analyze` (lines ~782–845): failure paths print verdicts; the success path
    prints `Overlaying <run> -> aligned.mcap` (+ raw query output) and returns
    with no closing verdict line.
  - `status()` docstring (line ~1281): "View JSON workspace status snapshot".
- `tools/e2e_status.py` lines 60–67:
  ```python
  speed = state.get("speed", 1.0)
  speed_txt = f" at {speed}x" if speed != 1.0 else ""
  ...
  lines.append(f"RUNNING {current_txt}{speed_txt}, last activity {age}")
  ```
- `tools/status.py:4` docstring: "Outputs JSON"; `justfile` (~line 75) comment
  "View JSON workspace status snapshot".
- `tests/unit/test_e2e_status.py` (~lines 79–80):
  `test_running_at_speed_names_the_factor` writes `speed=2.0` into a fake
  state and asserts the display — it exercises the branch being deleted.
- `tests/unit/test_preflight.py` — 6 existing characterization tests (plan
  036); follow their style for the new UDP tests.
- KEEP untouched: `tests/unit/test_sim_speed_validation.py` and any
  `wait_ready` tests that pin the "never call set_physics /
  PX4_SIM_SPEED_FACTOR" decision — they defend the plans/065 rejection and are
  NOT part of the dead plumbing.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Quality gate | `just check` | exit 0 |
| Preflight tests | `uv run pytest tests/unit/test_preflight.py -q` | all pass |
| e2e-status tests | `uv run pytest tests/unit/test_e2e_status.py -q` | all pass |
| Dead-name sweep | `rg -n "sim-stop" .` (repo, excluding plans/) | no matches outside plans/ |
| Dead-speed sweep | `rg -n "speed" tasks.py tools/e2e_status.py` | no physics-speed remnants |

## Scope

**In scope**:
- `tools/preflight.py`
- `tools/e2e_status.py`, `tools/status.py`
- `tasks.py` (the `speed` plumbing, the `sim-stop` comment, `analyze` verdict, `status` docstring)
- `justfile` (the one stale "JSON" comment)
- `tests/unit/test_preflight.py`, `tests/unit/test_e2e_status.py`

**Out of scope** (do NOT touch):
- `tools/wait_ready.py` — its set_physics refusal comment and validation are
  load-bearing history; nothing there is dead.
- `tests/unit/test_sim_speed_validation.py` — guards the 065 rejection.
- `sim/launch/_start_gz_px4.sh` — its `PX4_SIM_SPEED_FACTOR` warning comment
  stays.
- The e2e state-file schema beyond deleting the `speed` key.

## Git workflow

- Branch: `advisor/068-cli-hygiene`
- Commit style: `fix(tools): preflight probes UDP 8888; drop dead e2e speed plumbing; verdict papercuts`
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: UDP-aware port check in preflight

Add to `tools/preflight.py`:

```python
def _udp_port_free(port: int) -> bool:
    """A UDP port is free iff we can bind it (SO_REUSEADDR off)."""
    import socket as _socket

    s = _socket.socket(_socket.AF_INET, _socket.SOCK_DGRAM)
    try:
        s.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        s.close()
```

Switch the 8888 check to `_udp_port_free(8888)` and make `_port_pid` honor
`proto`: `["ss", "-lnup" if proto == "udp" else "-lntp", f"sport = :{port}"]`;
call `_port_pid(8888, "udp")`. Leave the 9090 TCP path on `_port_free`.

**Verify**: `uv run pytest tests/unit/test_preflight.py -q` → existing tests
pass (update any that pinned the old 8888 behavior). Live probe: in one shell
`python3 -c "import socket,time; s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM); s.bind(('127.0.0.1',18888)); time.sleep(30)" &`,
then `python3 -c "import sys; sys.path.insert(0,'tools'); from preflight import _udp_port_free; sys.exit(0 if not _udp_port_free(18888) else 1)"`
→ exit 0 (detects the occupied port).

### Step 2: Fix the dead `just sim-stop` remedy

Replace `just sim-stop` with `just stop` in both preflight messages
(lines ~123 and ~132) and rewrite the `tasks.py:679` comment to name
`just stop`.

**Verify**: `rg -n "sim-stop" tools/ tasks.py justfile` → no matches.

### Step 3: Delete the dead `--speed` plumbing

- `tasks.py`: `_e2e_run(configs: list[dict]) -> None` (drop the param); drop
  `"speed": speed` from the state write and `"speed": 1.0` from the detach
  seed; `e2e_worker()` loses the `speed` option and calls `_e2e_run(configs)`.
- `tools/e2e_status.py`: delete the `speed`/`speed_txt` lines; the RUNNING
  line becomes `f"RUNNING {current_txt}, last activity {age}"`.
- `tests/unit/test_e2e_status.py`: delete
  `test_running_at_speed_names_the_factor`; update any fixture state dicts
  that set `speed`.

**Verify**: `rg -n '"speed"|--speed|speed_txt' tasks.py tools/e2e_status.py tests/unit/test_e2e_status.py`
→ no matches. `uv run pytest tests/unit/test_e2e_status.py tests/unit/test_tasks_e2e_groups.py -q`
→ all pass.

### Step 4: Verdict papercuts

- `tools/status.py:4` docstring → "Concise English workspace snapshot (nodes,
  live status, capabilities)."; `tasks.py` `status()` docstring and the
  `justfile` comment likewise (drop "JSON").
- `tasks.py` `analyze` success path: after the overlay (and optional query)
  succeed, print a closing verdict, e.g.
  `print(f"ANALYZED {run_id}: aligned.mcap written" + (" + query ok" if query else ""))`
  — match the surrounding verdict tone (see the failure-path strings in the
  same function).

**Verify**: `rg -n "JSON workspace status" tasks.py justfile tools/status.py`
→ no matches. `just check` → exit 0.

## Test plan

- `test_preflight.py`: add `test_udp_port_free_detects_bound_socket` (bind a
  UDP socket on an ephemeral port in the test, assert `_udp_port_free` is
  False; close it, assert True). Add/adjust a test asserting the 8888 check
  path uses the UDP probe (follow the existing tests' structure — they fake
  or call the pure helpers directly).
- `test_e2e_status.py`: deletion of the speed test + fixtures still green.
- No test for the `analyze` verdict line (subprocess-heavy); the done
  criterion greps for it instead.

## Done criteria

- [ ] `uv run pytest tests/unit/test_preflight.py tests/unit/test_e2e_status.py -q` → all pass
- [ ] `rg -n "sim-stop" tools/ tasks.py justfile` → no matches
- [ ] `rg -n -- "--speed" tasks.py` → no matches
- [ ] `rg -n "speed" tools/e2e_status.py` → no matches
- [ ] `rg -n "ANALYZED" tasks.py` → one match on the analyze success path
- [ ] `just check` → exit 0
- [ ] `plans/README.md` status row updated

## STOP conditions

- `tests/unit/test_sim_speed_validation.py` fails after your change — you
  removed something load-bearing; restore and report.
- The e2e state file's `speed` key turns out to have a reader you didn't
  find (`rg '\bspeed\b' tools/ tests/ tasks.py` before deleting).
- Anything requires touching `tools/wait_ready.py`.

## Maintenance notes

- If faster-than-realtime ever returns, it comes back as the FROM-BOOT world
  SDF design (see plans/README round-6 notes and the rejected plan 065), never
  as a runtime flag — reviewers should reject any new `--speed` that reaches a
  running stack.
- The UDP probe binds the port briefly; it runs only in preflight (before any
  launch), so it cannot race the real agent.
