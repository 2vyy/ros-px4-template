# Plan 013: Write the SITL integration runbook (`docs/SKEIN.md`)

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving on. Touch
> only the files listed as in scope. If any STOP condition occurs, stop and
> report — do not improvise. When done, update the status row for this plan in
> `plans/README.md` — unless a reviewer dispatched you and told you they maintain
> the index.
>
> **Drift check (run first)**: `git diff --stat c211a0b..HEAD -- justfile tasks.py README.md`
> If `justfile`/`tasks.py`/`README.md` changed since this plan was written,
> compare the facts below (recipe names, command output) against the live files
> before writing; on a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P3
- **Effort**: S
- **Risk**: LOW (documentation only — no code, no behavior change)
- **Depends on**: plans 009, 010, 011, 012 (all merged — the runbook documents their combined, verified behavior)
- **Category**: docs
- **Planned at**: commit `c211a0b`, 2026-06-22

## Why this matters

Plans 009–012 built and verified a full pipeline — `just sim` records a per-run
ROS 2 bag + PX4 ULog, and `just analyze` reconciles them with skein into one
canonical timeline — but there is **no user-facing doc** explaining the workflow.
A template user who just ran `just sim` has no pointer to "now analyze it." This
is follow-up **#4** of the integration design at
`/home/ivy/Projects/skein/docs/template-integration-design.md`. It is a pure doc:
create `docs/SKEIN.md` (the end-to-end SITL runbook) and link it from `README.md`,
matching the repo's existing `docs/` conventions.

It lives in **this** repo (not skein) because every entry point (`just sim`,
`just stop`, `just analyze`) is a template command and a template operator is the
reader; it cross-links skein's design doc for the rationale.

## Current state

- `docs/` holds ALLCAPS topic docs: `FRAMES.md`, `TOPICS.md`, `MCP.md`,
  `MISSIONS.md`, `BACKLOG.md`. New doc → `docs/SKEIN.md` (match this naming).
- `README.md` has a `## Docs` bullet list (around line 142-148) linking those docs,
  and a `## Everyday commands` fenced block (around line 127-140). Add a bullet to
  the Docs list and an `analyze` line to Everyday commands. Existing Docs-list style:
  ```markdown
  ## Docs

  - [ENU / NED / body frames](docs/FRAMES.md)
  - [Topic owners and types](docs/TOPICS.md)
  - [rosbridge and ros-mcp-server](docs/MCP.md)
  - [Mission phases and YAML schema](docs/MISSIONS.md)
  ```
- The recipes that the runbook documents (verbatim from `justfile`, post-012):
  `sim *args`, `stop`, `analyze *args` (all route through `_run`, which
  auto-enters the `ubuntu` distrobox when host ROS is absent).
- The `analyze` command (in `tasks.py`): `analyze [RUN] [--query/-q EXPR]
  [--channel/-c TEXT] [--stats]`; `RUN` defaults to `latest`; skein dir defaults
  to the sibling `../skein`, overridable via `SKEIN_DIR`.

**Verified live facts to put in the runbook (run `20260622_112924`, 2026-06-22 —
these are real outputs; reproduce them as the example blocks, do not invent
others):**

- `just sim --overlay auto_arm` readiness verdict (tail):
  ```
  READY: /fmu topics up, rosbridge:9090, GCS params committed, recording -> logs/runs/20260622_112924/bag - 16.0s (logs/latest.log)
  ```
- `just stop` output:
  ```
  Copied PX4 ULog 16_29_22.ulg -> /home/ivy/Projects/ros-px4-template/logs/runs/20260622_112924/session.ulg
  STOPPED: 1 processes killed, 0 survivors
  ```
- Per-run artifacts after a recorded run:
  ```
  logs/runs/<run-id>/
    bag/                 # ros2 bag dir (metadata.yaml + bag_0.mcap)
    bag_record.log
    session.ulg          # the matching PX4 SITL ULog
    aligned.mcap         # written by `just analyze` (skein overlay output)
  logs/runs/latest -> <run-id>   # symlink to the most recent run
  ```
- `just analyze latest` (and `--query 'z < -1' --stats`) output:
  ```
  wrote .../logs/runs/20260622_112924/aligned.mcap (316082 records)
    wall_epoch   method=identity                 confidence=1.000
    sim_elapsed  method=clock_fit                confidence=1.000
    px4_boot     method=signal_match             confidence=0.907
  channel                 count  rate_hz  max_gap_s
  vehicle_local_position  12600  125      0.012
  ```
- Clock model (one line each; link skein's README clock model for detail):
  `wall_epoch` = identity (the canonical wall-time epoch), `sim_elapsed` =
  `clock_fit` (Gazebo `/clock`), `px4_boot` = `signal_match` (cross-correlates the
  bag's vs the ULog's `vehicle_local_position.z`; confidence ∈ [0,1] gates trust).
- Recorded topics: the minimum useful set (`/clock`,
  `/fmu/out/vehicle_local_position_v1`, `/fmu/out/vehicle_status_v1`,
  `/fmu/in/trajectory_setpoint`, `/fmu/in/offboard_control_mode`,
  `/fmu/in/vehicle_command`, `/drone/odom`, `/drone/target_pose`,
  `/drone/mission_status`) — defined in `tools/bag_recorder.py` `_BAG_TOPICS`;
  mirrors `docs/TOPICS.md`.

## Commands you will need

| Purpose             | Command                                          | Expected                          |
|---------------------|--------------------------------------------------|-----------------------------------|
| Confirm recipes     | `grep -nE '^(sim|stop|analyze)' justfile`        | matches the three recipes         |
| Confirm analyze opts| `grep -n 'def analyze' tasks.py`                 | matches                           |
| Link sanity         | `ls docs/SKEIN.md docs/TOPICS.md`                | both exist after Step 1           |
| Markdown smoke      | `grep -c '^#' docs/SKEIN.md`                      | ≥ 6 (has headings)                |

(No build/test needed — doc only. Do NOT run `just sim`/`just analyze`; you have
no distrobox. Use the verified outputs above verbatim.)

## Scope

**In scope** (only files to create/modify):
- `docs/SKEIN.md` (create) — the runbook.
- `README.md` (modify) — one bullet in `## Docs`, one line in `## Everyday commands`.
- `plans/README.md` (status row).

**Out of scope** (do NOT touch):
- Any code (`tasks.py`, `tools/`, `justfile`) — doc only.
- The skein repo at `/home/ivy/Projects/skein` — link to it, never edit it.
- Inventing command output — use only the verified blocks above. If you think an
  example is missing, note it for the reviewer rather than fabricating output.

## Git workflow
- Branch: `advisor/013-skein-sitl-integration-runbook`.
- Conventional commit, e.g. `docs(skein): SITL integration runbook (just sim -> just analyze)`.
- Do NOT push or open a PR.

## Steps

### Step 1: Write `docs/SKEIN.md`

Create the runbook with these sections (use the verified outputs above as the
example blocks). Target structure:

1. **Title + one-paragraph overview** — the template records each `just sim` run
   as a ROS 2 bag + matching PX4 ULog; [skein](https:///) (the sibling analysis
   tool) reconciles them onto one timeline. Link the design/rationale:
   `../skein/docs/template-integration-design.md` (note: relative to repo root;
   skein is the sibling `../skein`). State it is **SITL-only** (no flight
   controller required; ULog comes from PX4 SITL under `$PX4_DIR`).
2. **Prerequisites** — skein available at the sibling `../skein` (or set
   `SKEIN_DIR=/path/to/skein`); the `ubuntu` distrobox (recipes auto-enter it);
   `PX4_DIR` set in `.env` (already required by `just setup`).
3. **Record a run** — `just sim --overlay auto_arm` (or plain `just sim`). Show
   the READY verdict block (note the `recording -> logs/runs/<id>/bag` segment —
   that is plan 009's recorder). Mention `just log tail` to watch.
4. **Stop & capture the ULog** — `just stop`. Show the `Copied PX4 ULog … ->
   session.ulg` + `STOPPED … 0 survivors` block. Explain that teardown SIGINT-
   finalizes the bag (so the MCAP isn't truncated) and copies the run's PX4 ULog
   (plan 010, freshness-guarded).
5. **Per-run artifacts** — show the `logs/runs/<id>/` tree block and the `latest`
   symlink.
6. **Analyze** — `just analyze [<run>]` (default `latest`). Show the overlay
   output with the clock-reconciliation table. Explain the three domains
   (one line each) and that `px4_boot` confidence gates cross-clock trust.
7. **Query** — `just analyze latest --query '<expr>' --stats` and the
   `--channel/-c` option. Show the stats block. **Include the metacharacter note**:
   predicates with `<`/`>`/spaces now pass through correctly (fixed in the
   justfile arg forwarding); `--query 'z < -1'` works.
8. **What's recorded** — the `_BAG_TOPICS` list (from §Current state), noting it
   mirrors `docs/TOPICS.md`; link `docs/TOPICS.md`.
9. **Configuration** — `SKEIN_DIR` (default `../skein`), `--channel`, `--stats`,
   `--query`. One-run-per-`just sim`; `just clean` wipes `logs/runs/`.
10. **SITL-only & caveats** — no flight controller; ULog from
    `$PX4_DIR/build/px4_sitl_default/rootfs/log/`; recording is best-effort (never
    aborts `just sim`); bag rotation/size-caps are not implemented (long runs grow
    the bag); the graded skein surface (`delta`/`reports`/`parity`/`live --grade`)
    is a later, hardware-gated phase.
11. **Troubleshooting** — `no run at logs/runs/…` → record one with `just sim`
    first; `skein project not found …` → set `SKEIN_DIR`; `no session.ulg` warning
    → overlay proceeds bag-only (SITL may not have logged, or PX4_DIR wrong);
    `ros2 bag record -s mcap` plugin missing → install `ros-jazzy-rosbag2-storage-mcap`.
12. **See also** — `../skein/docs/template-integration-design.md`,
    `../skein/README.md` (clock model), and `plans/009`–`plans/012`.

Keep it operational and concise (a runbook, not a treatise). Use fenced code
blocks for every command and output.

**Verify**: `ls docs/SKEIN.md` → exists; `grep -c '^#' docs/SKEIN.md` → ≥ 6;
`grep -n 'just analyze' docs/SKEIN.md` → matches; `grep -n 'SKEIN_DIR' docs/SKEIN.md` → matches.

### Step 2: Link it from `README.md`

In the `## Docs` bullet list, add:

```markdown
- [Record & analyze a run with skein](docs/SKEIN.md)
```

In the `## Everyday commands` fenced block, add a line near the sim/stop commands:

```
just analyze                      # overlay+query the latest recorded run via skein
```

**Verify**: `grep -n 'docs/SKEIN.md' README.md` → matches (the Docs link);
`grep -n 'just analyze' README.md` → matches (the command line).

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `docs/SKEIN.md` exists with ≥ 6 headings (`grep -c '^#' docs/SKEIN.md`).
- [ ] `docs/SKEIN.md` contains the verified run-id `20260622_112924` example output, the `px4_boot … confidence=0.907` line, and the `SKEIN_DIR` config note (`grep -n` each).
- [ ] `docs/SKEIN.md` documents `just sim`, `just stop`, and `just analyze` (`grep -n` each).
- [ ] `README.md` links `docs/SKEIN.md` in the Docs list and has a `just analyze` line in Everyday commands.
- [ ] No code files changed — only `docs/SKEIN.md` and `README.md` (`git status` shows just those + nothing under `plans/` from you).
- [ ] `plans/README.md` status row updated.

## STOP conditions

Stop and report back (do not improvise) if:
- The recipe names or `analyze` options in `justfile`/`tasks.py` don't match
  §Current state (drift since `c211a0b`) — the doc would be wrong.
- You find yourself needing command output not provided in §Current state — do
  not fabricate it; report what's missing.
- Writing the runbook seems to require a code change — it does not; this is docs only.

## Maintenance notes

- The example outputs are pinned to run `20260622_112924`. If the recording topic
  set, the clock-domain names, or the `analyze` interface change, refresh the
  example blocks and `_BAG_TOPICS` list here.
- When the **graded surface** (`delta`/`reports`/`parity`/`live --grade`) is added
  in a later phase, extend this runbook with a "graded analysis" section rather
  than starting a new doc.
- Reviewer focus: confirm no fabricated output (every block traces to a verified
  fact in this plan), confirm links resolve (`docs/SKEIN.md`, `../skein/...`), and
  confirm it stays operational/concise.
