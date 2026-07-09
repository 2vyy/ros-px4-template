# Plan 037: Test `tools/gcs_heartbeat.py` and bring it back under the typecheck gate

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report - do not improvise. When done, update the status row for this plan
> in `plans/README.md` - unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat ead4cc6..HEAD -- tools/gcs_heartbeat.py tasks.py`
> If either changed, compare the "Current state" excerpts before proceeding;
> on a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: LOW-MED (removing a typecheck exclusion may surface errors)
- **Depends on**: none
- **Category**: tests
- **Planned at**: commit `ead4cc6`, 2026-07-06

## Why this matters

`tools/gcs_heartbeat.py` is what makes PX4 SITL armable: it sends MAVLink GCS
heartbeats and pushes the arming-enabler params (`COM_ARM_WO_GPS`,
`CBRK_SUPPLY_CHK`, `COM_SPOOLUP_TIME`, `EKF2_GPS_CHECK`), then writes
`/tmp/gcs_params_flag`, which `tools/wait_ready.py` uses as the third
readiness gate. A regression here fails every flight scenario opaquely
(scenarios just time out). It is currently excluded from BOTH gates: no unit
tests exist, and `tasks.py` passes `--exclude tools/gcs_heartbeat.py` to
`ty check`. This plan adds characterization tests for the pure parts and
removes the typecheck exclusion.

## Current state

- `tools/gcs_heartbeat.py` - the module. Key parts:
  - `_PARAMS_FLAG = Path("/tmp/gcs_params_flag")` (line 19).
  - `_PARAMS` table (lines 21-29): 4 tuples `(name, value, "INT32"|"REAL32")`.
    The comment above it records a hard-won constraint: do NOT push
    `SIM_GZ_EC_MIN` / `MPC_THR_*` (the old EC_MIN=0 override broke flight).
  - `_send_params(conn)` (lines 34-50): for INT32 params it packs the int
    big-endian and reinterprets the bytes as a float
    (`struct.pack(">i", ...)` then `struct.unpack(">f", ...)`) - the MAVLink
    param-value-as-float convention; REAL32 passes the float through. Calls
    `conn.mav.param_set_send(target_system, target_component, name_bytes,
    numeric_value, type_id)`.
  - `main()` (lines 53-136): network loop; NOT unit-testable, out of test scope.
- `tasks.py` ty invocation (around line 422-428):

```python
        [
            "uv", "run", "ty", "check",
            "src/core/ros_px4_template_core/lib",
            "tests/unit",
            "tools/",
            "--exclude", "tools/gcs_heartbeat.py",
        ],
```

- The file already carries `# type: ignore[unresolved-attribute]` comments on
  the pymavlink attribute accesses inside `main()` (lines 49, 63-64, 98-99),
  suggesting the exclusion may simply be stale.
- Test import pattern: `tests/conftest.py` puts `tools/` on `sys.path`;
  model imports/mocks on `tests/unit/test_wait_ready.py`.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| New tests | `uv run pytest tests/unit/test_gcs_heartbeat.py -q` | all pass |
| Typecheck just this file | `uv run ty check tools/gcs_heartbeat.py` | exit 0 (see Step 3) |
| Full gate | `just check` | exit 0 |
| Lint tasks.py | `uv run ruff check tasks.py` | exit 0 |

## Scope

**In scope**:
- `tests/unit/test_gcs_heartbeat.py` (create)
- `tasks.py` (remove the `--exclude` pair only)
- `tools/gcs_heartbeat.py` (ONLY type-annotation/`type: ignore` adjustments if
  ty requires them; zero behavior changes)

**Out of scope**:
- The `_PARAMS` values themselves - they are flight-verified (see the comment
  in the file); changing any value is forbidden.
- `tools/wait_ready.py` (its flag-gate is covered by its own tests).
- Networking code paths in `main()` - do not try to fake a MAVLink socket.

## Git workflow

- Branch: `advisor/037-gcs-heartbeat-tests`
- Commit style: `test(gcs): characterize param table and packing; re-enable ty`
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Create `tests/unit/test_gcs_heartbeat.py`

Note: the module imports `pymavlink` at top level; it is a project dependency
(preflight checks `import pymavlink` via uv), so plain import works under
`uv run pytest`. Tests:

1. `test_param_table_is_arming_enablers_only`: assert
   `{name for name, _, _ in gcs_heartbeat._PARAMS} ==
   {"COM_ARM_WO_GPS", "CBRK_SUPPLY_CHK", "COM_SPOOLUP_TIME", "EKF2_GPS_CHECK"}`
   and that no name starts with `SIM_GZ_` or `MPC_THR` (pins the
   verified-flight constraint documented in the file).
2. `test_param_types_valid`: every tuple's third element is `"INT32"` or
   `"REAL32"`; INT32 values are integral; all values are numeric.
3. `test_send_params_packs_int32_as_float_bits`: build a fake conn
   (`unittest.mock.MagicMock()` with `target_system=1`,
   `target_component=1`), call `gcs_heartbeat._send_params(fake)`, then for
   each call to `fake.mav.param_set_send` with an INT32 param, assert the sent
   float, repacked via `struct.pack(">f", v)` and unpacked with
   `struct.unpack(">i", ...)`, equals the original int (round-trip through
   float bits). For `COM_SPOOLUP_TIME` (REAL32) assert the value is sent as
   plain `0.0`.
4. `test_send_params_sends_all params_once`: `fake.mav.param_set_send.call_count == len(gcs_heartbeat._PARAMS)`.
5. `test_flag_path_constant`: `gcs_heartbeat._PARAMS_FLAG == Path("/tmp/gcs_params_flag")`
   (wait_ready and sim_cleanup share this literal; pin it so a rename cannot
   happen on one side only).

**Verify**: `uv run pytest tests/unit/test_gcs_heartbeat.py -q` -> 5 passed

### Step 2: Remove the ty exclusion

In `tasks.py`, delete the two argv elements `"--exclude",
"tools/gcs_heartbeat.py"` from the ty invocation.

**Verify**: `uv run ruff check tasks.py` -> exit 0

### Step 3: Make ty pass on the file (annotations only)

Run `uv run ty check tools/gcs_heartbeat.py`. If it reports errors:

- Prefer narrow `# type: ignore[<code>]` comments matching the style already
  in the file (lines 49, 63-64).
- Permitted: adding type annotations, `TYPE_CHECKING` imports.
- Forbidden: any change to runtime behavior, values, or control flow.

**Verify**: `uv run ty check tools/gcs_heartbeat.py` -> exit 0, and
`git diff tools/gcs_heartbeat.py` contains only comment/annotation lines.

### Step 4: Full gate

**Verify**: `just check` -> exit 0 (this now typechecks gcs_heartbeat as part
of `tools/`).

## Test plan

Step 1's five tests: the param allowlist (including the negative
SIM_GZ_/MPC_THR pin), type validity, the INT32-as-float-bits packing
round-trip, call count, and the shared flag path. Pattern:
`tests/unit/test_wait_ready.py` for imports/mocks.

## Done criteria

- [ ] `uv run pytest tests/unit/test_gcs_heartbeat.py -q` -> 5 passed
- [ ] `rg -n "exclude.*gcs_heartbeat" tasks.py` -> no matches
- [ ] `uv run ty check tools/gcs_heartbeat.py` -> exit 0
- [ ] `git diff tools/gcs_heartbeat.py` shows only annotations/`type: ignore` comments (or no changes)
- [ ] `just check` exits 0
- [ ] `plans/README.md` status row updated

## STOP conditions

- ty errors on `gcs_heartbeat.py` that cannot be resolved without behavior
  changes (report the error list; the exclusion stays until a human decides).
- `pymavlink` fails to import in the test environment (report; do not vendor
  or stub the import).
- The `_PARAMS` table differs from the 4 entries listed here (drift - the
  characterization targets moved).

## Maintenance notes

- Anyone adding a param to `_PARAMS` must update test 1's set - that is the
  point: the diff review question becomes "is this param flight-safe?".
- Reviewer: check no test asserts on `/tmp` file WRITES (only the constant);
  writing the real flag from a test could confuse a concurrently running sim.
