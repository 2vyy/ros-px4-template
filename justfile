# px4-ros-template task runner — run `just --list`
# -u off: ROS setup.bash references unset vars (e.g. AMENT_TRACE_SETUP_FILES)
set shell := ["bash", "-ec"]
set dotenv-load := true

PX4_DIR := env_var_or_default("PX4_DIR", "/home/ivy/robotics/PX4-Autopilot")
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
    uv run ty check src/core/ros_px4_template_core/lib tests/unit tools/

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
    cd {{PX4_DIR}} && git fetch --tags && git checkout {{version}} && git submodule update --recursive

clone-px4-msgs:
    #!/usr/bin/env bash
    set -euo pipefail
    if [ -d src/px4_msgs ]; then
      echo "src/px4_msgs already exists"
      exit 0
    fi
    git clone --branch "{{PX4_MSGS_BRANCH}}" --depth 1 https://github.com/PX4/px4_msgs.git src/px4_msgs

# Sim-only inspect stack (no RViz)
sim-inspect:
    mkdir -p {{LOG_DIR}}
    just sim world=inspect_aruco enable_vision=true

rviz-inspect:
    source {{ROS_SETUP}} && \
    source {{WS_INSTALL}} && \
    ros2 run rviz2 rviz2 -d config/rviz/inspect_mission.rviz

mission-status:
    source {{ROS_SETUP}} && \
    source {{WS_INSTALL}} && \
    ros2 topic echo /drone/mission_status

# Background sim + foreground RViz (waits for rosbridge :9090)
demo-inspect:
    #!/usr/bin/env bash
    set -euo pipefail
    mkdir -p "{{LOG_DIR}}"
    echo "Starting sim in background (inspect_aruco + vision)..."
    just sim world=inspect_aruco enable_vision=true &
    sim_pid=$!
    cleanup() {
      kill "$sim_pid" 2>/dev/null || true
      wait "$sim_pid" 2>/dev/null || true
    }
    trap cleanup EXIT INT TERM
    echo "Waiting for rosbridge on :9090..."
    for _ in $(seq 1 90); do
      if timeout 1 bash -c 'echo >/dev/tcp/127.0.0.1/9090' 2>/dev/null; then
        break
      fi
      sleep 2
    done
    if ! timeout 1 bash -c 'echo >/dev/tcp/127.0.0.1/9090' 2>/dev/null; then
      echo "ERROR: rosbridge did not open port 9090 in time" >&2
      exit 1
    fi
    echo "Launching RViz (Ctrl+C stops sim)..."
    source "{{ROS_SETUP}}"
    source "{{WS_INSTALL}}"
    ros2 run rviz2 rviz2 -d config/rviz/inspect_mission.rviz

# Headless sim (named recipe — avoids `just sim headless=true` parsing as world)
sim-stop:
    #!/usr/bin/env bash
    set -e
    pkill -f "ros2 launch.*sim_full" 2>/dev/null || true
    pkill -f "sim/launch/sim_full.launch.py" 2>/dev/null || true
    pkill -f "hardware/launch/hardware.launch.py" 2>/dev/null || true
    pkill -f "gz_px4_stack" 2>/dev/null || true
    pkill -f "/bin/px4" 2>/dev/null || true
    pkill -f "MicroXRCEAgent" 2>/dev/null || true
    pkill -f "gz sim" 2>/dev/null || true
    pkill -f "parameter_bridge" 2>/dev/null || true
    pkill -f "rosbridge_websocket" 2>/dev/null || true
    pkill -f "gcs_heartbeat" 2>/dev/null || true
    pkill -f "e2e_sim_test" 2>/dev/null || true
    pkill -f "install/ros_px4_template_core/lib/ros_px4_template_core/" 2>/dev/null || true
    pkill -f "install/px4_ros_sim/lib/px4_ros_sim/" 2>/dev/null || true
    sleep 2
    source {{ROS_SETUP}} 2>/dev/null || true
    ros2 daemon stop 2>/dev/null || true

sim-headless world="default" model="x500" enable_vision="false":
    just sim {{world}} {{model}} {{enable_vision}} true
