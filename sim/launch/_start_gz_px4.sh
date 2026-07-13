#!/usr/bin/env bash
# Start PX4 SITL (non-standalone); PX4's own rcS starts Gazebo and spawns the model.
#
# Invoked by sim/launch/sim_full.launch.py (_gz_px4_stack), which computes the
# paths and passes them as the environment variables this script reads:
#   PX4_BUILD          px4_sitl_default build dir (cd target; holds ./bin/px4)
#   GZ_PATHS           colon-joined GZ_SIM_RESOURCE_PATH
#   PX4_GZ_WORLDS_DIR  dir holding <world>.sdf (our sim/worlds or PX4's)
#   PX4_GZ_PLUGINS_DIR gz_plugins build dir
#   PX4_GZ_SERVER_CFG  PX4 gz server.config path
#   SIM_WORLD SIM_MODEL  world and model names
#   SIM_WORLD_SDF      absolute path to the resolved <world>.sdf
#   WORLD_IS_REPO      "1" when SIM_WORLD_SDF lives in our sim/worlds, else empty
#   HEADLESS_FLAG      "1" for headless, else empty
#
# Default (PX4-shipped) worlds: we do NOT pre-start `gz sim`. PX4 runs WITHOUT
# PX4_GZ_STANDALONE, so its rcS starts Gazebo late in boot via
# ${PX4_GZ_WORLDS}/${world}.sdf and immediately attaches gz_bridge, a clean
# lockstep boot. This path is byte-identical to before and stays that way.
#
# Repo-only worlds (WORLD_IS_REPO=1): PX4's rcS clobbers PX4_GZ_WORLDS to its own
# dir (via gz_env.sh), so it can never open our sim/worlds/<w>.sdf. We use PX4's
# first-class "gazebo already running" branch instead: pre-start a PAUSED gz
# server on the repo SDF, let PX4 detect and adopt it (that branch never sources
# gz_env.sh, so no clobber), then unpause once PX4 has spawned the model. Pausing
# is load-bearing: an unpaused pre-start free-ran ~7-9 s before PX4 attached,
# corrupting IMU/baro timing to EKF2 divergence and a phantom altitude runaway
# (plans/065). A paused server with no late-unpause deadlocked. This branch does
# both: paused server + unpause on model-spawn. Flight uses stock thrust
# calibration (no SIM_GZ_EC_MIN / MPC_THR overrides), verified to hold altitude.
set -e

export GZ_IP=127.0.0.1

# CRITICAL: never export PX4_SIM_SPEED_FACTOR, and never call the gz set_physics
# service on a running stack (not from here, not from wait_ready, not by hand).
# The env var makes PX4's rcS (px4-rc.gzsim) call set_physics; and ANY set_physics
# call, even with values identical to the running physics and issued pre-arm on a
# grounded vehicle, latently corrupts PX4's altitude estimate: z runs away to
# kilometers once the vehicle arms (verified 2026-07-11, plans/065 spike truth
# table). Physics settings come solely from the world SDF loaded at boot.

export GZ_SIM_RESOURCE_PATH="$GZ_PATHS"
export PX4_GZ_WORLDS="$PX4_GZ_WORLDS_DIR"
export PX4_GZ_PLUGINS="$PX4_GZ_PLUGINS_DIR"
export PX4_GZ_SERVER_CONFIG="$PX4_GZ_SERVER_CFG"
export GZ_SIM_SERVER_CONFIG_PATH="$PX4_GZ_SERVER_CFG"
export GZ_SIM_SYSTEM_PLUGIN_PATH="$PX4_GZ_PLUGINS_DIR"
export LD_LIBRARY_PATH="$PX4_GZ_PLUGINS_DIR:${LD_LIBRARY_PATH}"

# Applied at STARTUP (reliable) rather than via gcs_heartbeat over lossy UDP.
# Arming/EKF reliability: allow GPS fusion without strict SITL checks, arm w/o GPS.
# Keep in lockstep with tools/gcs_heartbeat.py:_PARAMS (runtime re-send copy);
# the parity test in test_gcs_heartbeat.py fails if these two lists drift.
export PX4_PARAM_COM_ARM_WO_GPS=1
export PX4_PARAM_CBRK_SUPPLY_CHK=894281
export PX4_PARAM_COM_SPOOLUP_TIME=0.0
export PX4_PARAM_EKF2_GPS_CHECK=0
export PX4_PARAM_EKF2_GPS_CTRL=7
# NOTE: do NOT override SIM_GZ_EC_MIN / MPC_THR_HOVER / MPC_THR_MIN here.
# Stock x500 airframe defaults (EC_MIN=150, MPC_THR_HOVER=0.60) produce stable
# offboard altitude hold, verified against bare PX4 SITL. The earlier overrides
# (EC_MIN=0, MPC_THR_HOVER=0.15) came from a debunked "idle approx hover" theory
# and actually broke flight (no liftoff / runaway). Keep stock thrust calibration.

if [ "$HEADLESS_FLAG" = "1" ]; then
  export HEADLESS=1
fi

if [ "$WORLD_IS_REPO" = "1" ]; then
  # Repo world: PX4 cannot open it (gz_env.sh clobbers PX4_GZ_WORLDS), so we
  # pre-start a PAUSED server and let PX4 adopt it via its "already running" branch.
  echo "[sim_full] Pre-starting paused gz server for repo world '$SIM_WORLD' ($SIM_WORLD_SDF)"
  gz sim --verbose=1 -s "$SIM_WORLD_SDF" &   # NO -r: server starts paused
  if [ "$HEADLESS_FLAG" != "1" ]; then
    gz sim -g &                              # GUI client, mirrors PX4 rcS when not headless
  fi
  # Wait for the world to advertise its clock (this is PX4's own detection probe).
  for _ in $(seq 1 60); do
    gz topic -l 2>/dev/null | grep -qx "/world/${SIM_WORLD}/clock" && break
    sleep 0.5
  done
  # Unpause watcher (forked before the exec below, so it survives). The strongest
  # "PX4 attached and spawned" signal is the model instance existing; once it does,
  # release physics so sim time barely advanced before lockstep.
  (
    for _ in $(seq 1 120); do
      if gz model --list 2>/dev/null | grep -q "${SIM_MODEL}_0"; then
        break
      fi
      sleep 0.5
    done
    sleep 1  # let gz_bridge finish attaching to the freshly spawned model
    gz service -s "/world/${SIM_WORLD}/control" --reqtype gz.msgs.WorldControl \
      --reptype gz.msgs.Boolean --timeout 2000 --req 'pause: false'
    echo "[sim_full] repo world '${SIM_WORLD}' unpaused"
  ) &
fi

echo "[sim_full] Starting PX4 (it starts Gazebo in lockstep) world='$SIM_WORLD' model='$SIM_MODEL'"

cd "$PX4_BUILD"
# Boot from stock airframe defaults every time (determinism): clear any params
# persisted by a prior run so flight behaviour never drifts between launches.
rm -f rootfs/parameters*.bson 2>/dev/null || true
exec env PX4_GZ_WORLD="$SIM_WORLD" PX4_SIM_MODEL="gz_${SIM_MODEL}" ./bin/px4
