# ros-px4-template

A ROS 2 + PX4 + Gazebo project template with modern Python toolchains.

This repository provides a pre-configured template for rapid drone software development while still maintaining an organized, performant, and tested codebase.

## Core design principles

- **Stack**
  - Ubuntu 24.04 (native, [distrobox](https://distrobox.it), WSL)
  - ROS 2 Jazzy and Gazebo Harmonic
  - PX4 with Micro XRCE-DDS
    - Upstream PX4 Autopilot lives outside this repo (`PX4_DIR` in `.env`). Gazebo worlds and models go in `sim/`.
    - `src/px4_msgs` is pinned to branch `release/1.17` and never edited locally.
  - Python 3.12 with [uv](https://github.com/astral-sh/uv), [ruff](https://github.com/astral-sh/ruff), and [ty](https://github.com/astral-sh/ty)
  - [just](https://github.com/casey/just) for development workflows
  - [ros-mcp-server](https://github.com/robotmcp/ros-mcp-server) for live topic and service inspection via rosbridge
- All `src/` code is sim/hardware agnostic. Nothing under `src/` imports from `sim/` or `hardware/`.
- All internal coordinates follow [ROS REP-103](https://www.ros.org/reps/rep-0103.html) ENU frame. Conversion to and from PX4 NED happens only at the PX4 boundary in `offboard_controller` and `mission_manager`.
- Scenario integration tests in `tests/scenarios/` validate the capabilities of the current codebase. Verified milestones are recorded in `tests/capabilities.toml`.
- Live topics are checked against the defined topic manifest in [docs/TOPICS.md](docs/TOPICS.md) with `just log topics` to prevent interface drift.
- All processes stream to one logfmt session log, `logs/latest.log` (every line `t=<rel_s> src=<source> ...`). `just log summary` regenerates `logs/latest_summary.json` (run arc, errors, per-scenario pass/fail).

## Runtime architecture

```mermaid
flowchart TD
    subgraph agent_layer ["Agent & Inspection Tooling"]
        Bridge["rosbridge (Port 9090)"]
        MCP["ros-mcp-server"]
    end

    subgraph ros_layer ["ROS 2 Jazzy (px4_ros_core)"]
        mission["mission_manager\n(YAML to ENU Pose)"]
        offboard["offboard_controller\n(ENU to NED Transform)"]
    end

    subgraph px4_layer ["PX4 v1.17 Autopilot"]
        XRCE["MicroXRCE Agent (Port 8888)"]
        SITL["PX4 SITL\n(Offboard Mode)"]
    end

    subgraph sim_layer ["Simulation"]
        Gazebo["Gazebo Harmonic"]
    end

    %% Simulation & Autopilot Loop
    Gazebo <--> SITL
    SITL <-->|DDS| XRCE

    %% Control Flow
    mission -->|ENU Target Pose| offboard
    XRCE -->|Telemetry (_v1 topics)| offboard
    offboard -->|NED Position Setpoints| XRCE

    %% Tooling Integration
    ros_layer -->|ROS Topics & Services| Bridge
    Bridge --> MCP
```



## Quick start

1. Copy the environment template and edit paths for your machine:

```bash
cp .env.example .env       # then edit .env: PX4_DIR, ROS_SETUP, PX4_VERSION
```

1. Initialize and build:

```bash
just setup            # clones px4_msgs, uv sync, rosdep, and builds
```

1. Launch the full simulation stack:

```bash
just sim start              # Gazebo (headless), PX4 SITL, XRCE, ROS nodes, rosbridge
```

1. With the sim loaded, run a scenario and record the capability:

```bash
just run 01_arm_takeoff
just cap record arm_takeoff
```

1. Stop everything:

```bash
just stop
```

## Project structure

```
ros-px4-template/
├── src/
│   ├── core/
│   │   └── ros_px4_template_core/   # Core nodes + lib (sim/hardware agnostic)
│   │       ├── nodes/               # offboard_controller, mission_manager, position_node, ...
│   │       └── lib/                 # frames, mission/ engine, StructuredLogger
│   ├── px4_ros_msgs/                # Custom msgs (ControllerStatus, MissionStatus)
│   └── px4_msgs/                    # Upstream PX4 micro XRCE defs (release/1.17)
├── sim/                             # Gazebo worlds, models, sim_full.launch.py
├── hardware/                        # Serial FC + rosbridge; no Gazebo
├── config/
│   ├── params/                      # sim/hardware overlays; path_file, enable_marker_hover
│   ├── paths/                       # ENU waypoint lists only
│   └── missions/                    # data-driven mission YAML state graphs (see docs/MISSIONS.md)
├── vehicles/                        # vehicle configurations (e.g. x500.yaml)
├── tests/
│   ├── scenarios/                   # Live acceptance tests on a running graph
│   ├── unit/                        # Pure logic (no ROS graph)
│   └── capabilities.toml            # Verified capability registry
├── tools/                           # capabilities CLI, log summarizer, topic checker, ...
├── docs/                            # FRAMES, TOPICS, MCP, MISSIONS, ...
├── AGENTS.md                        # Agent operating guide (this repo)
├── justfile
├── tasks.py                         # core CLI orchestrator
├── pyproject.toml                   # uv, ruff, ty
└── uv.lock                          # frozen dependencies
```

## Everyday commands

```bash
just                              # live status snapshot + where to go next
just setup                        # one-time setup (px4_msgs, uv, rosdep, build)
just check                        # format, lint, typecheck, build, unit tests
just sim start                    # boot headless sim detached, wait until ready, return
just sim start --gui              # same, with the Gazebo GUI
just stop                         # exhaustive cold teardown of the whole stack
just run <name>                   # one scenario, supervised (e.g. 01_arm_takeoff)
just e2e                          # full headless cycle (--detach for background)
just wait run                     # bounded wait on the active run/cycle (exit 3 = still going)
just runs                         # recent run records: id, verdict, reason, age
just log since                    # new log lines since your last call (events+errors)
just mission validate <name>      # validate a mission YAML in <1s, no sim
just cap show                     # print derived capability rungs
just cap plan [claim]             # print the dependency-first claims frontier
just cap record <claim>           # commit fresh PASS evidence after a scenario
just log summary                  # regenerate latest_summary.json
just log topics                   # audit live topics vs docs/TOPICS.md
just analyze                      # overlay+query the latest recorded run via skein
```

## Docs

- [Agent workflows, invariants, troubleshooting](AGENTS.md)
- [ENU / NED / body frames](docs/FRAMES.md) 
- [Topic owners and types](docs/TOPICS.md)
- [rosbridge and ros-mcp-server](docs/MCP.md)
- [Mission phases and YAML schema](docs/MISSIONS.md)
- [Claims ladder and committed evidence](docs/CLAIMS.md)
- [Authoring a challenge from a rules doc](docs/CHALLENGES.md)
- [Record & analyze a run with skein](docs/SKEIN.md)
- [Competition worlds and ArUco assets](docs/SIM.md)

