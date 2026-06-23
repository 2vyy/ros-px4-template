# px4-ros-template task runner — run `just --list`
set shell := ["bash", "-ec"]
set positional-arguments
set dotenv-load := true
ROS_SETUP := env_var_or_default("ROS_SETUP", "/opt/ros/jazzy/setup.bash")
WS_INSTALL := justfile_directory() / "install/setup.bash"

# Default recipe: list all workflows
default:
    @just --list

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

# Boot the sim stack detached, wait until ready, print a verdict, and return
sim *args:
    @just _run sim "$@"

# Exhaustive cold teardown of the whole stack (no process survives)
stop:
    @just _run stop

# Analyze a recorded run with skein (overlay bag+ULog; optional --query)
analyze *args:
    @just _run analyze "$@"

# Connect to serial hardware flight controller
hw *args:
    @just _run hw "$@"

# Verification suite (unit tests, live scenario <name>, or e2e headless cycles)
test *args:
    @just _run test "$@"

# Run a specific scenario test directly by name (e.g. just scenario 01_arm_takeoff)
scenario name:
    @just _run scenario "{{name}}"

# Scaffold a runnable Scenario stub at tests/scenarios/<name>.py
scenario-new *args:
    @just _run scenario-new "$@"

# View JSON workspace status snapshot (nodes, live status, capabilities)
status:
    @just _run status

# Manage verified capabilities registry (show, mark)
cap *args:
    @just _run cap "$@"

# Observability hub (merge logs, watch/tail logs, or validate live topic graph)
log *args:
    @just _run log "$@"

# List, validate, or describe mission YAML graphs (no sim needed)
mission *args:
    @just _run mission "$@"
