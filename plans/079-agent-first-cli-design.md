# Agent-first CLI redesign

Date: 2026-07-17
Status: approved design, not yet implemented

## Problem

The current CLI grew by accretion: ~17 flat `just` recipes with inconsistent
shapes (`scenario` vs `scenario-status` vs `e2e-status` vs `test e2e`), no
guarantee that a mission run ever terminates, and no cheap way for an agent to
follow a live run. The two failure modes for an agent driver:

1. A blocking command holds the terminal; if the mission wedges, the harness
   kills the call at its timeout (Claude Code Bash: 120s default, 600s max)
   and the agent learns nothing.
2. A detached command returns immediately; the agent must re-grep the log
   every N seconds, which costs a tool call per peek and gives no signal for
   when to stop.

Reference for agent-CLI ergonomics: axi.md's 10 principles (token-efficient
output, minimal default fields, truncation with size hints, pre-computed
aggregates, definitive empty states, structured errors and exit codes,
content first, contextual disclosure).

## Core insight

The blocking-vs-detached question is a false dilemma once two facts are used:

1. The real invariant is "no command may be unbounded". If every run is
   supervised by a watchdog that always produces a terminal verdict, blocking
   is safe (the command ends before the harness kills it) and detaching is
   safe (there is always a terminal state to wait for).
2. Claude Code's `run_in_background` re-invokes the agent when the process
   exits. A bounded-blocking command launched in the background gives push
   semantics: terminal not captured, zero polling, wake-up at the verdict.

## Decisions (locked)

| Question | Decision |
|----------|----------|
| Harness coupling | Agnostic core, Claude-Code-aware. Bounded `wait` verbs work for any agent; the `run_in_background` pattern is documented as the preferred workflow on top. No hard coupling. |
| Surface | Full regrammar. `just` stays as the env/distrobox shim; recipes are regenerated around noun-verb commands. |
| Run identity | Mission/scenario executions get lightweight run records. Boot sessions stay latest-only: one `logs/latest.log`, clobbered per boot, as today. |

## Command surface

| Command | Behavior | Bounded by |
|---------|----------|------------|
| `just` (bare) | Content first: live status snapshot (stack, current run, last verdict) plus suggested next actions, then a `--list` hint | instant |
| `just setup` / `check` / `build` / `clean` | Unchanged | already bounded |
| `just test` | Unit tests only. The `test e2e` and `test scenario` forms die | already bounded |
| `just sim start [flags]` | Today's `just sim`: detached boot, readiness wait, verdict, return. Same flags | `--timeout` |
| `just hw start [flags]` | Today's `just hw` | same |
| `just stop` | One global cold teardown for sim or hw. Two nouns do not need two teardowns | instant |
| `just run <name> [--detach] [--timeout N]` | Run one scenario under the run supervisor. Blocks by default but guaranteed bounded; `--detach` returns after a `RUN STARTED` verdict | supervisor deadline |
| `just e2e [--detach]` | Full cycle (manages boots, claims-DAG order). Same block/detach contract as today's `test e2e` | per-run supervisors plus cycle deadline |
| `just runs` | Table of recent run records: id, verdict, reason, age. Definitive empty state ("no runs recorded") | instant |
| `just wait ready [--timeout N]` | Block until stack readiness | `--timeout` |
| `just wait run [<id>] [--timeout N]` | Block until the latest (or named) run reaches a terminal verdict. Timeout prints the heartbeat snapshot and exits 3: a status report, not an error | `--timeout`, default well under 600s |
| `just log since\|events\|summary\|topics\|tail [--run id]` | See Log access | instant, except `tail` (human-only) |
| `just cap show\|plan\|record` | Unchanged | instant |
| `just mission list\|validate\|show\|sim\|schema` | Unchanged (offline YAML tooling) | bounded |
| `just scenario-new`, `analyze`, `gen-markers`, `gen-world` | Unchanged | bounded |

Deleted: `just scenario`, `just scenario-status`, `just e2e-status`,
`just test e2e`, bare `just sim`, `just status` (bare `just` replaces it).
`wait run` plus `runs` subsume both status commands.

### Exit codes

Existing repo codes are kept (0 success, 1 ran-but-failed, 2 usage,
3 precondition). `wait run` maps onto them exactly as `e2e-status` does
today: 0 terminal PASS, 1 terminal FAIL/STUCK/ABORTED, 2 no such run,
3 still running at timeout.

## Termination guarantee (the stuck-mission fix)

Three layers make "never ends" structurally impossible:

1. **Mission YAML deadlines.** Per-phase `timeout_s` guard plus a global
   `deadline_s`. Breach transitions to an abort phase (land, disarm) and
   emits `event=MISSION_ABORT reason=phase_timeout phase=<name>`. Bounds the
   onboard behavior itself, which also matters on hardware.
2. **Run supervisor.** Every `just run` executes under a parent process that
   enforces a hard deadline and a liveness watchdog (heartbeat not advancing
   for ~20s kills the run with verdict `STUCK`). Generalizes the existing e2e
   supervisor; `just e2e` becomes a loop of supervised runs plus boot
   management.
3. **Verdict-file contract.** `logs/runs/<name>_<ts>.json` holding
   `{verdict, reason, t_start, t_end, last_phase, detail}` is always written,
   via finally/trap. If the supervisor is SIGKILLed, `wait run` detects
   dead-pid-without-verdict and synthesizes `ABORTED`.

`STUCK` is a first-class third verdict, distinct from `FAIL`. FAIL means
"flew and missed criteria, read the mission events". STUCK means "something
wedged, read the stack log". The verdict line says which path to take.

The supervisor rewrites a one-line heartbeat file every second (t, phase,
armed, alt, last event and its age). `wait`, `runs`, and bare `just` read
files only, never ROS, so they are instant and safe to call reflexively.

## Execution model / harness contract

- Portable path (any agent): `just run X` blocks and will end. For long
  cycles: `just e2e --detach`, then repeated `just wait run --timeout 120`;
  each window that times out returns progress, not an error.
- Claude Code fast path (documented in AGENTS.md): launch `just run X` or
  `just e2e` via `run_in_background`; the harness re-invokes the agent when
  the verdict lands. Zero polling, terminal never captured.
- Stated contract in AGENTS.md: every command is bounded. The only
  intentionally unbounded command is `just log tail`, labeled human-only.

## Log access

`logs/latest.log` (logfmt, clobbered per boot) stays the substrate and `rg`
stays the raw escape hatch. New verbs:

- `just log since`: lines appended since the last call (one cursor file;
  single-agent assumption). Default view is events plus errors only, with a
  trailer aggregate: `9 events shown (214 raw lines this window, 0 errors);
  --raw for all`. This is "tail without the -f": the agent-side replacement
  for polling greps.
- `just log events [--run <id>]`: events view of the whole session, or
  sliced to a run's t-range from its record.
- `just log summary`: kept as-is (arc summary, auto-printed after e2e).
- `just log topics`, `just log tail`: kept as-is.

Every verdict and every wait timeout ends with contextual disclosure: one or
two concrete next commands, e.g.
`FAIL hover_hold drift_m=0.31; next: just log events --run hover_hold_1432`.

## Run records

- Location: `logs/runs/<name>_<ts>.json` plus one heartbeat file at
  `logs/heartbeat` (current run only, rewritten each second). Not
  committed (logs/ is gitignored). Keep last N (e.g. 50), prune oldest on
  write.
- A new boot clobbers `latest.log` but not the run records, so verdict
  history survives; only the raw log slice of pre-boot runs is lost, which
  matches how debugging actually happens (autopsy now, not archaeology).
- `just cap record` gains the run id in its evidence payload; the claims
  flow is otherwise unchanged.

## Ripple effects

- `tools/check_docs.py` `_SUBCOMMANDS` learns the new sub-apps
  (`sim`, `run`, `wait`, `log`) and drops the dead ones.
- AGENTS.md and README command tables regenerate around the new grammar,
  including the harness contract section.
- Net simplification: two status commands, two test forms, and the bespoke
  e2e state machinery collapse into supervisor + verdict files + `wait` and
  `runs`.

## Deferred (backlog, not this design)

- `just log why`: walk back from the last FAIL/STUCK verdict to the first
  anomaly and print that window.
- `just wait --until event=<pattern>`: arbitrary event waits.
- Boot-session archiving (`logs/<ts>/` per boot with pruning).
- TOON or other token-optimized structured output; logfmt is fine for now.
