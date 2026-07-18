# Challenge authoring

Hand an agent a competition rules document; walk this loop to a verified
scenario. Worlds and marker maps come from one challenge-spec YAML so they
cannot disagree. Missions and scenarios stay hand-authored (schema +
`just mission sim` / `just scenario-new` already cover them).

See also: [docs/CLAIMS.md](CLAIMS.md), [docs/SIM.md](SIM.md),
[docs/MISSIONS.md](MISSIONS.md).

## 1. Input (extract from the rules doc)

| Extract | Why |
|---------|-----|
| Arena geometry (bounds, gates, obstacles) | Spec YAML obstacles + keep-out guards |
| Marker ids and positions (anchored-ENU) | Spec YAML markers; DICT_4X4_50 ids 0-49 |
| Required maneuvers (takeoff, hover, land, search) | Mission phases + scenario `done()` |
| Time / altitude limits | Mission guards (`time_budget`, `altitude_ceiling`) |
| Scoring events | Claim entries with `source` + `params` |

## 2. The loop

Claims first. Decompose the rules into registry entries before writing SDF or
mission YAML; `just cap plan <challenge>` is the live build order from then on.

| Step | File(s) | Command | Verify |
|------|---------|---------|--------|
| 1. Claims | `tests/capabilities.toml` | Edit: one composite per scored task (`source`, `params`, `requires`) plus missing leaf claims; see [CLAIMS.md](CLAIMS.md) | `just check`; `just cap plan <challenge>` prints the frontier |
| 2. Spec | `sim/worlds/specs/<name>.yaml` | Author markers + optional static obstacles | Spec loads (`just gen-world --spec ...`) |
| 3. Marker models | `sim/models/aruco_marker_<id>/` | `just gen-markers --ids <id>,...` if ids are new | Model dirs exist |
| 4. World + map | `sim/worlds/<name>.sdf`, `config/marker_maps/<name>.yaml` | `just gen-world --spec sim/worlds/specs/<name>.yaml` | Paths printed; origin climb column clear |
| 5. Install map | share dir via rebuild | `just check` | Build installs `config/marker_maps/*.yaml` |
| 6. Mission | `config/missions/<name>.yaml` | Author against [MISSIONS.md](MISSIONS.md) schema | `just mission validate <name>`; `just mission sim <name>` |
| 7. Overlay (optional) | `config/params/overlays/<name>.yaml` | Only if params differ from sim defaults | Overlay name resolves under `just sim --overlay` |
| 8. Scenario | `tests/scenarios/<NN>_<name>.py` | `just scenario-new <NN>_<name>`; edit `done()`; real `detail` in `write_report` | Stub runs; claim points at `scenario_file` |
| 9. Claim boot fields | same `capabilities.toml` entry | Set `sim_world` / `sim_model` / `sim_vision` / `mission` | `just cap show` lists the claim |
| 10. Live | — | `just scenario <name>` | PASS verdict with real detail |
| 11. E2E (optional) | — | `just test e2e` | Aggregate PASS; evidence auto-recorded if tree clean |
| 12. Record | `tests/evidence/<claim>/` | `just cap record <claim>` (or rely on e2e auto-record) | `just cap show` at `sim-flown`; commit the evidence file |

Do **not** invent a mission YAML generator or a scenario generator beyond
`just scenario-new`. Those are the agent's authoring work.

## 3. Docs to update

| Change | Doc |
|--------|-----|
| New world | [SIM.md](SIM.md) world table row |
| New / changed topics | [TOPICS.md](TOPICS.md) + node ROS 2 Interface docstring |
| New behaviors / guards | [MISSIONS.md](MISSIONS.md) tables + regenerate schema (`just mission schema > schemas/mission.schema.json`) |
| New claim | `tests/capabilities.toml` only (rungs are derived; see CLAIMS.md) |

## 4. Representable vs verifiable

**Representable.** The sim can host arbitrary static geometry and ArUco
layouts: pylons, boxes, pads, marker fields. Physics is real-time only
(world SDF is the sole speed authority; see plans/065). No moving actors.

**Verifiable.** The stack can only assert what it can sense. Perception is a
single nadir camera: real pixels need `--model x500_mono_cam_down` on a
marker world; otherwise scenarios use synthetic detections. Obstacles are
physical collision hazards but are **not** perceived (no avoidance sensor —
reactive avoidance challenges are out of template scope). Rules assertions
use the guards in [MISSIONS.md](MISSIONS.md), including `altitude_ceiling`,
`time_budget`, and `keep_out_box` (plan 073). Scenario-side continuous
sampling uses `HeldThroughout` from `tests/scenarios/_common.py`.

## 5. Worked example: `gate_run`

Rules sketch: "two gate pylons at x=2 m, y=±1.5 m; markers 0 at (8,0) and 3
at (5,0)."

```bash
# 1. Claims first (composite + leaves) — edit tests/capabilities.toml, then:
just cap plan gate_run   # or your composite id

# 2-4. Spec already at sim/worlds/specs/gate_run.yaml
just gen-markers --ids 3
just gen-world --spec sim/worlds/specs/gate_run.yaml
just check

# Live boot of the generated world (no mission/scenario required for READY):
just sim --world gate_run
just log topics
just stop

# 6-12. Author mission + scenario against the claim frontier, then:
# just mission sim <name>
# just scenario <NN>_<name>
# just cap record <claim>
```

`gate_run` is the generator smoke world committed by plan 072. Extending it
into a scored claim (mission + scenario + evidence) is follow-on authoring,
not generator work.
