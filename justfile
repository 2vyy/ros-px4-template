# px4-ros-template task runner — run `just --list`
set shell := ["bash", "-ec"]
set positional-arguments
set dotenv-load := true
ROS_SETUP := env_var_or_default("ROS_SETUP", "/opt/ros/jazzy/setup.bash")
WS_INSTALL := justfile_directory() / "install/setup.bash"

# Default: live status snapshot + where to go next
default:
    @just _run snapshot

# Sourced environment executor (auto-delegates to Distrobox if ROS is missing on host)
_run *args:
    @if [ ! -f "{{ROS_SETUP}}" ] && command -v distrobox >/dev/null 2>&1; then \
        distrobox enter ubuntu -- bash -lc 'cd "$1" && shift && exec just _run "$@"' _ "{{justfile_directory()}}" "$@"; \
    else \
        source {{ROS_SETUP}} && \
        (source {{WS_INSTALL}} 2>/dev/null || true) && \
        unset VIRTUAL_ENV && \
        uv run tasks.py "$@"; \
    fi

# One-time workspace setup (auto-detects PX4 version, runs uv sync and rosdep)
setup:
    @just _run setup

# Complete quality gate (auto-formats, auto-fixes lints, typechecks, compiles workspace, and runs unit tests)
check:
    @just _run check

# Compile the workspace using colcon build
build:
    @just _run build

# Wipe build artifacts, build logs, and per-run logs
clean:
    @just _run clean

# Simulation stack lifecycle (sim start [flags]; boots detached, waits, verdicts)
sim *args:
    @just _run sim "$@"

# Exhaustive cold teardown of the whole stack (no process survives)
stop:
    @just _run stop

# Hardware stack lifecycle (hw start [flags])
hw *args:
    @just _run hw "$@"

# Run unit tests
test:
    @just _run test

# Run one scenario under the run supervisor (bounded; always leaves a run record)
run *args:
    @just _run run "$@"

# Recent run records: id, verdict, reason, age
runs:
    @just _run runs

# Full headless e2e cycle (blocks; --detach for background + just wait run)
e2e *args:
    @just _run e2e "$@"

# Bounded waits (wait ready | wait run); a timeout is a status report, not an error
wait *args:
    @just _run wait "$@"

# Scaffold a runnable Scenario stub at tests/scenarios/<name>.py
scenario-new *args:
    @just _run scenario-new "$@"

# Manage derived capability claims (show, plan, record)
cap *args:
    @just _run cap "$@"

# Observability hub (merge logs, watch/tail logs, or validate live topic graph)
log *args:
    @just _run log "$@"

# List, validate, or describe mission YAML graphs (no sim needed)
mission *args:
    @just _run mission "$@"

# Generate ArUco marker model assets (see docs/SIM.md)
gen-markers *args:
    uv run python tools/gen_marker_assets.py {{args}}

# Generate a Gazebo world + marker map from a challenge spec (see docs/CHALLENGES.md)
gen-world *args:
    uv run python tools/gen_world.py {{args}}
