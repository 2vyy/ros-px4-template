# Plan 056: `gcs_heartbeat` confirms params via PARAM_VALUE read-back before writing the READY flag

> **Executor instructions**: Follow this plan step by step, verifying each
> step. On any STOP condition, stop and report. When done, update
> `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 01f94c7..HEAD -- tools/gcs_heartbeat.py tests/unit/test_gcs_heartbeat.py`
> On any mismatch with the excerpts below, STOP. Plan 055 edits the same file
> (adds `EKF2_GPS_CTRL` to `_PARAMS`) — if 055 already landed, its version IS
> the expected current state.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: MED (touches boot timing; a too-strict ack loop could delay or hang READY)
- **Depends on**: 055 (same file; land 055 first)
- **Category**: bug (tooling)
- **Planned at**: commit `01f94c7`, 2026-07-10

## Why this matters

`wait_ready` treats `/tmp/gcs_params_flag` as "PX4 params committed (PX4
ready)". But `gcs_heartbeat` writes the flag after merely *sending* the
`param_set` messages 5× over lossy UDP — no acknowledgment. If the sends are
dropped, arming enablers (`COM_ARM_WO_GPS`, `EKF2_GPS_CHECK`, …) are not
applied, yet the stack reports READY; arming scenarios then fail
intermittently with no diagnostic pointing at the cause. MAVLink already
defines the confirmation mechanism: PX4 replies to each `PARAM_SET` with a
`PARAM_VALUE` message echoing the new value.

Note: `_start_gz_px4.sh` also applies the same params via `PX4_PARAM_*` env at
boot (the "reliable" path), so in practice the GCS overlay is a belt-and-
braces re-application — which is exactly why a silent failure here has never
been *observed*, and why the fix must not make boot slower or flakier than
the status quo (see the fallback in Step 2).

## Current state

`tools/gcs_heartbeat.py:93-99`:

```python
# Retry param_set a few times — UDP is lossy.
for _ in range(5):
    _send_params(conn)
    time.sleep(0.3)

_PARAMS_FLAG.write_text(str(time.time()))
print("[gcs_heartbeat] Params committed. Sending heartbeats...", flush=True)
```

`_send_params` (`:39-56`) iterates `_PARAMS` calling
`conn.mav.param_set_send(...)` with INT32 values byte-packed into the float
field (the `struct.pack(">i", ...)`/`unpack(">f", ...)` dance at `:43-45` —
this is the MAVLink param union convention; the read-back must decode
PARAM_VALUE the same way for INT32 params).

The re-send path (`:134-141`) after a PX4 restart writes the flag the same
unconfirmed way.

`pymavlink` API available on `conn` (mavutil.mavudp):
`conn.mav.param_request_read_send(target_system, target_component, name.encode(), -1)`
and `conn.recv_match(type="PARAM_VALUE", blocking=True, timeout=...)`.

Existing tests: `tests/unit/test_gcs_heartbeat.py` — 5 tests (plus plan 055's
parity test). They test pure pieces with fakes; follow that pattern (no real
sockets in unit tests).

## Commands you will need

| Purpose | Command | Expected |
|---------|---------|----------|
| Quality gate | `just check` | exit 0 |
| Targeted | `uv run pytest tests/unit/test_gcs_heartbeat.py -q` | all pass |
| Boot timing (live) | `time just sim` | READY in ~15-20 s (no regression >5 s vs. a baseline run before your change) |

## Scope

**In scope**:
- `tools/gcs_heartbeat.py`
- `tests/unit/test_gcs_heartbeat.py`
- `tools/wait_ready.py` docstring lines 8-9 only (wording: "committed and confirmed")

**Out of scope**:
- `_PARAMS` contents (055 owns that) and the flag path (deferred by design)
- `wait_ready` gating logic (055 added mtime freshness; unchanged here)
- `sim/launch/_start_gz_px4.sh`

## Git workflow

- Branch: `advisor/056-gcs-param-ack`
- Commit style: `fix(sim): confirm PX4 param sets via PARAM_VALUE before declaring params committed`

## Steps

### Step 1: Extract a testable confirm loop

Add a pure-ish function (fakeable `conn`):

```python
def _confirm_params(conn: mavutil.mavudp, timeout_s: float = 5.0) -> tuple[bool, list[str]]:
    """Request each _PARAMS entry back; return (all_confirmed, missing_names).

    Decodes INT32 PARAM_VALUEs with the same byte-union convention _send_params
    uses. A param counts confirmed when the echoed value matches.
    """
```

Implementation sketch: for each `(name, value, type_str)` in `_PARAMS`, send
`param_request_read_send`, then drain `PARAM_VALUE` matches until the name
appears or a per-param deadline passes; compare decoded value (INT32: pack
the received float back with `struct.pack(">f", ...)`/`unpack(">i", ...)`;
REAL32: `math.isclose(..., rel_tol=1e-6)`). Collect misses.

### Step 2: Wire it with a safe fallback

Replace the blind send block:

```python
for attempt in range(3):
    _send_params(conn)
    ok, missing = _confirm_params(conn)
    if ok:
        break
if ok:
    print("[gcs_heartbeat] Params confirmed by PX4.", flush=True)
else:
    # Do not hold the boot hostage: boot-time PX4_PARAM_* env exports already
    # applied these (see _start_gz_px4.sh). Log loudly and proceed.
    print(f"[gcs_heartbeat] WARNING: params NOT confirmed: {missing} "
          "(boot-time env exports remain in effect)", flush=True)
_PARAMS_FLAG.write_text(str(time.time()))
```

The flag is still written on the warn path — READY semantics keep working on
lossy links, but the log now distinguishes confirmed vs. attempted, which is
the diagnostic that was missing. Apply the same confirm to the re-send path
(`:134-141`).

**Verify**: `just check` → exit 0.

### Step 3: Unit tests

With a fake `conn` (records sent requests; returns queued PARAM_VALUE
objects), following the existing fake style in `test_gcs_heartbeat.py`:

- all params echo correctly → `(True, [])`
- one param never echoes → `(False, ["EKF2_GPS_CHECK"])` within the timeout
- INT32 byte-union round trip: value 894281 (CBRK_SUPPLY_CHK) survives
  pack/unpack both directions
- REAL32 close-comparison accepts 0.0

**Verify**: `uv run pytest tests/unit/test_gcs_heartbeat.py -q` → all pass
(≥9 now).

### Step 4: Live timing check (operator/distrobox)

Baseline BEFORE merging: `time just sim` on main. Then on the branch:
`time just sim` → READY; `rg "Params confirmed" logs/latest.log` → 1 match;
wall time within +5 s of baseline. `just scenario 01_arm_takeoff` → PASS.

## Done criteria

- [ ] `_confirm_params` exists, unit-tested incl. INT32 union round-trip
- [ ] Flag write is preceded by a confirm attempt on BOTH the initial and re-send paths; warn path logs missing names
- [ ] `just check` exit 0; live boot shows "Params confirmed" and no >5 s regression
- [ ] `plans/README.md` row updated

## STOP conditions

- PX4 SITL does not answer `PARAM_REQUEST_READ` on the GCS link (no
  PARAM_VALUE ever arrives live) — capture `rg gcs logs/latest.log` and stop;
  the fallback keeps behavior safe but the plan's premise needs review.
- Boot time regresses >5 s consistently — the drain loop is eating heartbeat
  cadence; report rather than tune blindly.

## Maintenance notes

- If a future param is added with a type other than INT32/REAL32, the
  decode branch must be extended — the parity test from 055 names the lists,
  this plan's round-trip test is the template.
- Reviewer: check the confirm loop cannot starve heartbeats (PX4 drops the
  GCS link after ~3 s of silence — the loop must keep `heartbeat_send`
  cadence or complete well under that; simplest is confirming within the
  existing 0.3 s-spaced attempts).
