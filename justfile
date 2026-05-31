# px4-ros-template task runner — run `just --list`
set shell := ["bash", "-ec"]
set dotenv-load := true
ROS_SETUP := env_var_or_default("ROS_SETUP", "/opt/ros/jazzy/setup.bash")
WS_INSTALL := justfile_directory() / "install/setup.bash"

# Sourced environment executor
_run *args:
    source {{ROS_SETUP}} && \
    (source {{WS_INSTALL}} 2>/dev/null || true) && \
    uv run tasks.py {{args}}

# One-time workspace setup (auto-detects PX4 version, runs uv sync and rosdep)
setup:
    @just _run setup

# Complete quality gate (auto-formats, auto-fixes lints, typechecks, compiles workspace, and runs unit tests)
check:
    @just _run check

# Simulation & hardware runner (gui, headless, bg, px4 standalone, edit, hardware connections, or stop processes)
sim *args:
    @just _run sim {{args}}

# Verification suite (unit tests, live scenario <name>, or e2e headless cycles)
test *args:
    @just _run test {{args}}

# Observability hub (summary, window, grep, errors, tail, merge, events, status, topics, and capabilities)
log *args:
    @just _run log {{args}}

# Replay a recorded rosbag against the live ROS graph
replay bag *args:
    @just _run replay {{bag}} {{args}}
