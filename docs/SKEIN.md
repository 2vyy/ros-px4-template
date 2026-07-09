# Record & analyze a SITL run with skein

## Overview

`just sim --record` records a ROS 2 bag (the bridge/agent topics) and, on
teardown, captures the matching PX4 SITL ULog. A default `just sim` records
nothing; recording is opt-in for runs you plan to inspect with `just analyze`.
Those two recorded logs share no clock: the bag is wall time, the ULog is PX4
boot time, and Gazebo may be running faster or slower than real time.
[skein](../../skein) — installed as a sibling repo — reconciles both logs onto
one canonical timeline so you can query across ROS and PX4 data as if they were
one recording.

This doc is the operational runbook: record, stop, inspect artifacts,
analyze, query. For the design rationale (why a separate tool, why this
clock model, how the template and skein interfaces were co-designed), see
[`../skein/docs/template-integration-design.md`](../../skein/docs/template-integration-design.md).

This workflow is **SITL-only**. There is no flight controller in the loop;
the ULog comes from PX4 SITL running under `$PX4_DIR`, not a real autopilot.

## Prerequisites

- skein checked out as a sibling repo at `../skein` (i.e. next to this repo's
  directory), or set `SKEIN_DIR=/path/to/skein` to point elsewhere.
- The `ubuntu` distrobox — `just sim`, `just stop`, and `just analyze` all
  route through `_run`, which auto-enters the distrobox when host ROS isn't
  present. You don't need to enter it manually.
- `PX4_DIR` set in `.env`, pointing at your PX4 source checkout (needed for
  SITL to run and for `just stop` to find the ULog under
  `$PX4_DIR/build/px4_sitl_default/rootfs/log/`).

## 1. Record a run

```bash
just sim --record --overlay auto_arm
```

Recording is opt-in; a default `just sim` records nothing and `just analyze`
requires a `--record` run. Once the stack is up, the readiness verdict confirms
recording started:

```
READY: /fmu topics up, rosbridge:9090, GCS params committed, recording -> logs/runs/20260622_112924/bag - 16.0s (logs/latest.log)
```

The `recording -> logs/runs/<id>/bag` segment is the per-run bag recorder
(see plan 009). Tail the live log with:

```bash
just log tail
```

## 2. Stop & capture the ULog

```bash
just stop
```

Teardown sends SIGINT to finalize the bag cleanly, then copies the run's
PX4 ULog (freshness-guarded — it only copies a ULog written during this
run; see plan 010):

```
Copied PX4 ULog 16_29_22.ulg -> /home/ivy/Projects/ros-px4-template/logs/runs/20260622_112924/session.ulg
STOPPED: 1 processes killed, 0 survivors
```

## 3. Per-run artifacts

After a recorded run, `logs/runs/<run-id>/` contains:

```
logs/runs/<run-id>/
  bag/                 # ros2 bag dir (metadata.yaml + bag_0.mcap)
  bag_record.log
  session.ulg          # the matching PX4 SITL ULog
  aligned.mcap          # written by `just analyze` (skein overlay output)
logs/runs/latest -> <run-id>   # symlink to the most recent run
```

`logs/runs/latest` always points at the most recent run, so you can refer to
runs by id or just say `latest`.

## 4. Analyze

```bash
just analyze            # equivalent to: just analyze latest
just analyze 20260622_112924
```

This overlays the run's bag + ULog with skein and writes
`logs/runs/<run>/aligned.mcap`:

```
wrote .../logs/runs/20260622_112924/aligned.mcap (316082 records)
  wall_epoch   method=identity                 confidence=1.000
  sim_elapsed  method=clock_fit                confidence=1.000
  px4_boot     method=signal_match             confidence=0.907
```

Three clock domains get reconciled onto the canonical timeline:

- **`wall_epoch`** — `identity`. The canonical wall-time epoch; everything
  else is mapped onto this.
- **`sim_elapsed`** — `clock_fit`. Fit against Gazebo's `/clock` topic, which
  may run faster/slower than wall time.
- **`px4_boot`** — `signal_match`. PX4 boot-time, with no shared epoch to the
  bag at all — skein cross-correlates the bag's and the ULog's
  `vehicle_local_position.z` signal to find the time offset. The
  `confidence` (0–1) reflects how good that correlation was; low confidence
  means don't trust the PX4-derived alignment for that run.

For the full clock-model writeup, see
[`../skein/README.md`](../../skein/README.md).

## 5. Query

```bash
just analyze latest --query 'z < -1' --stats
just analyze latest --query 'z < -1' --channel vehicle_local_position --stats
```

`--query`/`-q` runs `skein query --where <expr>` against the aligned MCAP;
`--channel`/`-c` selects which channel to query (default
`vehicle_local_position`); `--stats` prints per-channel aggregates:

```
channel                 count  rate_hz  max_gap_s
vehicle_local_position  12600  125      0.012
```

Note: predicates containing `<`, `>`, or spaces (e.g. `'z < -1'`) are passed
through correctly — justfile argument forwarding was fixed for this, so you
don't need to escape or avoid metacharacters.

## What's recorded

The bag records this minimum useful topic set (defined in
`tools/bag_recorder.py`'s `_BAG_TOPICS`, mirroring
[`docs/TOPICS.md`](TOPICS.md)):

```
/clock
/fmu/out/vehicle_local_position_v1
/fmu/out/vehicle_status_v1
/fmu/in/trajectory_setpoint
/fmu/in/offboard_control_mode
/fmu/in/vehicle_command
/drone/odom
/drone/target_pose
/drone/mission_status
```

## Configuration

- `SKEIN_DIR` — path to the skein checkout. Default: `../skein` (sibling of
  this repo). Override if skein lives elsewhere.
- `UV_PROJECT_ENVIRONMENT` — where skein's uv venv lives. By default `just
  analyze` picks a per-environment path under your cache
  (`~/.cache/ros-px4-template/skein-venv/<env>`, keyed on host vs. the distrobox
  container) so the host (e.g. Python 3.14) and the container (Python 3.12)
  don't rebuild a shared `<skein>/.venv` on every switch. Export it yourself to
  override.
- `--query` / `-q` — a `skein query --where` expression to run against the
  aligned MCAP.
- `--channel` / `-c` — which channel `--query` applies to (default
  `vehicle_local_position`).
- `--stats` — print per-channel rate/gap aggregates instead of (or alongside)
  query results.
- Each `just sim --record` produces exactly one run under `logs/runs/<id>/`.
  `just clean` wipes `logs/runs/` entirely.

## SITL-only & caveats

- No flight controller is involved — this is PX4 SITL only. The ULog comes
  from `$PX4_DIR/build/px4_sitl_default/rootfs/log/`.
- Recording is best-effort: if the bag recorder fails to start or the ULog
  can't be found/copied, `just sim` / `just stop` still complete — recording
  never aborts the sim.
- Bag rotation / size caps are not implemented. Long-running sessions will
  grow the bag file without bound.
- skein's graded analysis surface (`delta`, `reports`, `parity`, `live
  --grade`) is a later, hardware-gated phase and is out of scope for this
  SITL runbook.

## Troubleshooting

- `no run at logs/runs/…` — record a run first with `just sim --record` (or
  `just sim --record --overlay auto_arm`) before analyzing.
- `skein project not found …` — set `SKEIN_DIR=/path/to/skein` if skein
  isn't checked out as a sibling at `../skein`.
- `Warning: no session.ulg for this run` — overlay proceeds bag-only. Either
  PX4 SITL didn't log this run, or `PX4_DIR` is misconfigured.
- `ros2 bag record -s mcap` plugin missing — install
  `ros-jazzy-rosbag2-storage-mcap`.

## See also

- [`../skein/docs/template-integration-design.md`](../../skein/docs/template-integration-design.md) — design rationale
- [`../skein/README.md`](../../skein/README.md) — skein's clock model in detail
- `plans/009`–`plans/012` — the plans that built this pipeline (bag recording,
  ULog capture on teardown, the `analyze` command, argument-forwarding fix)
