# px4-ros-template task runner — run `just --list`
# -u off: ROS setup.bash references unset vars (e.g. AMENT_TRACE_SETUP_FILES)
set shell := ["bash", "-ec"]
set dotenv-load := true

PX4_DIR := env_var_or_default("PX4_DIR", "")
PX4_VERSION := env_var_or_default("PX4_VERSION", "v1.17.0")
PX4_MSGS_BRANCH := env_var_or_default("PX4_MSGS_BRANCH", "release/1.17")
ROS_SETUP := env_var_or_default("ROS_SETUP", "/opt/ros/jazzy/setup.bash")
WS_INSTALL := justfile_directory() / "install/setup.bash"
LOG_DIR := justfile_directory() / "logs"
GZ_RESOURCE := justfile_directory() / "sim/worlds:" + justfile_directory() / "sim/models:" + PX4_DIR + "/Tools/simulation/gz/worlds:" + PX4_DIR + "/Tools/simulation/gz/models"

# Paths passed to ruff (excludes src/px4_msgs — generated/upstream messages)
RUFF_PATHS := "src/core src/px4_ros_sim tests tools sim hardware"

alias s := sim
alias hw := hardware
alias b := build
alias l := lint

default:
    @just --list

build:
    source {{ROS_SETUP}} && \
    colcon build \
        --symlink-install \
        --cmake-args -DCMAKE_BUILD_TYPE=RelWithDebInfo \
        --event-handlers console_direct+

build-incremental:
    source {{ROS_SETUP}} && \
    colcon build --symlink-install --packages-up-to ros_px4_template_core px4_ros_msgs px4_ros_sim

clean:
    rm -rf build/ install/ log/

sim world="default" model="x500" enable_vision="false" headless="false":
    mkdir -p {{LOG_DIR}}
    source {{ROS_SETUP}} && \
    source {{WS_INSTALL}} && \
    export GZ_IP=127.0.0.1 && \
    export GZ_SIM_RESOURCE_PATH="{{GZ_RESOURCE}}:${GZ_SIM_RESOURCE_PATH:-}" && \
    ([ "{{headless}}" = "true" ] && export HEADLESS=1 || true) && \
    ros2 launch {{justfile_directory()}}/sim/launch/sim_full.launch.py \
        world:={{world}} \
        model:={{model}} \
        enable_vision:={{enable_vision}} \
        headless:={{headless}} \
        log_dir:={{LOG_DIR}} \
        2>&1 | tee {{LOG_DIR}}/sim_$(date +%Y%m%dT%H%M%S).log

sim-px4 world="default" model="x500" headless="false":
    : "${PX4_DIR:?PX4_DIR not set — create .env with PX4_DIR=/path/to/PX4-Autopilot}" && \
    export GZ_IP=127.0.0.1 && \
    export GZ_SIM_RESOURCE_PATH="{{GZ_RESOURCE}}:${GZ_SIM_RESOURCE_PATH:-}" && \
    export PX4_GZ_WORLDS="{{PX4_DIR}}/Tools/simulation/gz/worlds" && \
    export PX4_GZ_MODELS="{{PX4_DIR}}/Tools/simulation/gz/models" && \
    export PX4_GZ_PLUGINS="{{PX4_DIR}}/build/px4_sitl_default/src/modules/simulation/gz_plugins" && \
    export PX4_GZ_SERVER_CONFIG="{{PX4_DIR}}/src/modules/simulation/gz_bridge/server.config" && \
    export GZ_SIM_SYSTEM_PLUGIN_PATH="$PX4_GZ_PLUGINS" && \
    export GZ_SIM_SERVER_CONFIG_PATH="$PX4_GZ_SERVER_CONFIG" && \
    export LD_LIBRARY_PATH="$PX4_GZ_PLUGINS:${LD_LIBRARY_PATH:-}" && \
    ([ "{{headless}}" = "true" ] && export HEADLESS=1 || true) && \
    cd {{PX4_DIR}}/build/px4_sitl_default && \
    PX4_GZ_WORLD={{world}} \
    PX4_SIM_MODEL=gz_{{model}} \
    ./bin/px4

xrce:
    MicroXRCEAgent udp4 -p 8888

gazebo-edit world="default":
    #!/usr/bin/env bash
    set -euo pipefail
    : "${PX4_DIR:?PX4_DIR not set — create .env with PX4_DIR=/path/to/PX4-Autopilot}"
    export GZ_SIM_RESOURCE_PATH="{{GZ_RESOURCE}}:${GZ_SIM_RESOURCE_PATH:-}"
    local_world="sim/worlds/{{world}}.sdf"
    px4_world="{{PX4_DIR}}/Tools/simulation/gz/worlds/{{world}}.sdf"
    if [[ -f "$local_world" ]]; then
      exec gz sim "$local_world"
    elif [[ -f "$px4_world" ]]; then
      exec gz sim "$px4_world"
    else
      echo "No world SDF for {{world}} (checked $local_world and $px4_world)" >&2
      exit 1
    fi

hardware port="/dev/ttyUSB0" baud="921600":
    source {{ROS_SETUP}} && \
    source {{WS_INSTALL}} && \
    ros2 launch {{justfile_directory()}}/hardware/launch/hardware.launch.py \
        serial_port:={{port}} \
        baudrate:={{baud}} \
        use_sim_time:=false \
        config:=hardware \
        log_dir:={{LOG_DIR}}

lint:
    uv run ruff check {{RUFF_PATHS}}
    uv run ruff format --check {{RUFF_PATHS}}

fix:
    uv run ruff check --fix {{RUFF_PATHS}}
    uv run ruff format {{RUFF_PATHS}}

typecheck:
    uv run ty check src/core/ros_px4_template_core/lib tests/unit tools/ --exclude tools/gcs_heartbeat.py

check-invariants:
    uv run python tools/check_invariants.py

check: lint check-invariants typecheck test-unit

test-unit:
    uv run pytest tests/unit/ -v

scenario name:
    source {{ROS_SETUP}} && \
    source {{WS_INSTALL}} && \
    uv run python tests/scenarios/{{name}}.py

mark-capability capability platform:
    uv run python tools/capabilities.py mark {{capability}} {{platform}}

capabilities:
    uv run python tools/capabilities.py show

merge-logs:
    uv run python tools/log_merger.py --log-dir {{LOG_DIR}} --output {{LOG_DIR}}/merged.jsonl
    @echo "Merged: {{LOG_DIR}}/merged.jsonl"

tail-logs:
    uv run python tools/log_watch.py --log-dir {{LOG_DIR}}

check-topics:
    source {{ROS_SETUP}} && \
    source {{WS_INSTALL}} && \
    uv run python tools/check_topics.py --manifest docs/TOPICS.md

rviz:
    source {{ROS_SETUP}} && \
    source {{WS_INSTALL}} && \
    ros2 run rviz2 rviz2 -d config/rviz/default.rviz

setup:
    @echo "Installing dev tools with uv..."
    uv sync --group dev
    @echo "Installing rosdep dependencies..."
    source {{ROS_SETUP}} && rosdep install --from-paths src --ignore-src -r -y
    @echo "Building workspace..."
    just build
    @echo "Done. Run: just sim"

update-px4 version=PX4_VERSION:
    : "${PX4_DIR:?PX4_DIR not set — create .env with PX4_DIR=/path/to/PX4-Autopilot}" && \
    cd {{PX4_DIR}} && git fetch --tags && git checkout {{version}} && git submodule update --recursive

clone-px4-msgs:
    #!/usr/bin/env bash
    set -euo pipefail
    if [ -d src/px4_msgs ]; then
      echo "src/px4_msgs already exists"
      exit 0
    fi
    git clone --branch "{{PX4_MSGS_BRANCH}}" --depth 1 https://github.com/PX4/px4_msgs.git src/px4_msgs

# [human] Sim-only inspect stack (no RViz)
sim-inspect:
    mkdir -p {{LOG_DIR}}
    just sim world=inspect_aruco enable_vision=true

# [human] Open world SDF in RViz for the inspect_aruco mission
rviz-inspect:
    source {{ROS_SETUP}} && \
    source {{WS_INSTALL}} && \
    ros2 run rviz2 rviz2 -d config/rviz/inspect_mission.rviz

# [human] Stream /drone/mission_status to terminal
mission-status:
    source {{ROS_SETUP}} && \
    source {{WS_INSTALL}} && \
    ros2 topic echo /drone/mission_status

# [human] Background sim + foreground RViz (inspect_aruco with vision)
demo-inspect:
    #!/usr/bin/env bash
    set -euo pipefail
    mkdir -p "{{LOG_DIR}}"
    echo "Starting sim in background (inspect_aruco + vision)..."
    just sim world=inspect_aruco enable_vision=true &
    sim_pid=$!
    cleanup() {
      kill "$sim_pid" 2>/dev/null || true
      just sim-stop 2>/dev/null || true
    }
    trap cleanup EXIT INT TERM
    just wait-ready
    echo "Launching RViz (Ctrl+C stops sim)..."
    source "{{ROS_SETUP}}"
    source "{{WS_INSTALL}}"
    ros2 run rviz2 rviz2 -d config/rviz/inspect_mission.rviz

# SIGTERM all sim processes, SIGKILL survivors, verify clean. Exits 1 if any remain.
sim-stop:
    source {{ROS_SETUP}} 2>/dev/null || true && \
    uv run python tools/sim_cleanup.py

# List any live sim/ROS/gz processes — use to verify sim-stop worked.
ps-check:
    #!/usr/bin/env bash
    patterns=(
      "ros2 launch.*sim_full" "sim_full.launch.py" "hardware.launch.py"
      "/bin/px4" "MicroXRCEAgent" "gz sim" "parameter_bridge"
      "rosbridge_websocket" "install/ros_px4_template_core/lib"
    )
    found=0
    for pat in "${patterns[@]}"; do
      pids=$(pgrep -f "$pat" 2>/dev/null || true)
      if [[ -n "$pids" ]]; then
        echo "LIVE  [$pat]: $pids"
        found=1
      fi
    done
    if [[ $found -eq 0 ]]; then
      echo '{"clean": true}'
    fi

sim-headless world="default" model="x500" enable_vision="false":
    just sim {{world}} {{model}} {{enable_vision}} true

# Start headless sim in background (own session), write PID to logs/sim.pid. Use `just sim-stop` to terminate.
sim-bg world="default" model="x500" enable_vision="false":
    #!/usr/bin/env bash
    set -euo pipefail
    mkdir -p "{{LOG_DIR}}"
    pidfile="{{LOG_DIR}}/sim.pid"
    if [[ -f "$pidfile" ]] && kill -0 "$(cat "$pidfile")" 2>/dev/null; then
        echo "{\"error\": \"sim already running\", \"pid\": $(cat "$pidfile"), \"hint\": \"just sim-stop\"}"
        exit 1
    fi
    log_file="{{LOG_DIR}}/sim_$(date +%Y%m%dT%H%M%S).log"
    setsid bash -c "
        source '{{ROS_SETUP}}'
        source '{{WS_INSTALL}}'
        export GZ_IP=127.0.0.1
        export GZ_SIM_RESOURCE_PATH='{{GZ_RESOURCE}}:\${GZ_SIM_RESOURCE_PATH:-}'
        export HEADLESS=1
        exec ros2 launch '{{justfile_directory()}}/sim/launch/sim_full.launch.py' \
            world:={{world}} model:={{model}} enable_vision:={{enable_vision}} \
            headless:=true log_dir:='{{LOG_DIR}}'
    " >"$log_file" 2>&1 < /dev/null &
    sim_pid=$!
    echo "$sim_pid" > "$pidfile"
    echo "{\"started\": true, \"pid\": $sim_pid, \"log\": \"$log_file\", \"pidfile\": \"$pidfile\"}"

# Remove per-node JSONL logs, run summary, and scenario reports for a clean-slate run.
clean-logs:
    rm -f {{LOG_DIR}}/*.jsonl {{LOG_DIR}}/run_summary.json {{LOG_DIR}}/scenario_*.json {{LOG_DIR}}/sim.pid

# Block until rosbridge :9090 open and /fmu/out/vehicle_local_position is live.
wait-ready timeout="180":
    source {{ROS_SETUP}} && \
    source {{WS_INSTALL}} && \
    uv run python tools/wait_ready.py --timeout {{timeout}}

# Prerequisite checks before launching the sim (ports, paths, px4_msgs branch).
preflight:
    uv run python tools/preflight.py

# Full headless e2e cycle: clean-logs, preflight, sim, wait-ready, all scenarios, check-topics, merge-logs.
e2e:
    #!/usr/bin/env bash
    set -uo pipefail
    just clean-logs
    just preflight
    just sim-bg
    cleanup() { just sim-stop 2>/dev/null || true; }
    trap cleanup EXIT INT TERM
    just wait-ready
    fails=0
    for s in 01_arm_takeoff 02_hover_hold 03_waypoint; do
        just scenario "$s" || fails=$((fails+1))
    done
    just check-topics || true
    just merge-logs
    just e2e-report
    exit $fails

# Compact JSON snapshot: sim alive, live nodes, last scenarios, last log event.
status:
    source {{ROS_SETUP}} 2>/dev/null || true && \
    source {{WS_INSTALL}} 2>/dev/null || true && \
    uv run python tools/status.py

# Events-only from merged log (~50 tokens). Run just merge-logs first.
log-events:
    #!/usr/bin/env bash
    merged="{{LOG_DIR}}/merged.jsonl"
    if [[ ! -f "$merged" ]]; then
        echo '{"empty": true, "help": ["just merge-logs"]}'
        exit 0
    fi
    python3 -c "
    import json, sys
    for line in open('$merged', encoding='utf-8'):
        r = json.loads(line)
        if r.get('level') in ('EVENT', 'ERROR'):
            row = {k: v for k, v in r.items() if k not in ('ros_ts', 't_first', 't_last')}
            print(json.dumps(row, separators=(',', ':')))
    "

# Combined pass/fail report across all scenarios + key timeline events.
e2e-report:
    uv run python tools/e2e_report.py

# Tail the last N lines of a specific node's JSONL log (default 50).
node-log node lines="50":
    #!/usr/bin/env bash
    f="{{LOG_DIR}}/{{node}}.jsonl"
    if [[ ! -f "$f" ]]; then
        echo "{\"error\": \"no log for node '{{node}}'\", \"available\": [$(ls {{LOG_DIR}}/*.jsonl 2>/dev/null | xargs -n1 basename | sed 's/.jsonl//' | paste -sd',' | sed 's/,/\",\"/g; s/^/\"/; s/$/\"/' || echo)]}"
        exit 1
    fi
    tail -n {{lines}} "$f" | python3 -c "
    import json, sys
    for line in sys.stdin:
        r = json.loads(line)
        print(json.dumps({k: v for k, v in r.items() if k != 'ros_ts'}, separators=(',', ':')))
    "
