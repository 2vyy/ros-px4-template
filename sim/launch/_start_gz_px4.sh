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
#   SIM_SPEED          real-time speed factor as a string (e.g. 1.0)
#   HEADLESS_FLAG      "1" for headless, else empty
#
# We do NOT pre-start `gz sim`. PX4 runs WITHOUT PX4_GZ_STANDALONE, so its rcS
# starts Gazebo late in boot via ${PX4_GZ_WORLDS}/${world}.sdf and immediately
# attaches gz_bridge, giving a clean lockstep boot. Pre-starting gz ourselves let
# it free-run ~7-9 s before PX4 attached, corrupting IMU/baro timing to EKF2
# divergence to a phantom altitude runaway. Flight uses stock thrust calibration
# (no SIM_GZ_EC_MIN / MPC_THR overrides), verified to hold altitude.
set -e

export GZ_IP=127.0.0.1

# CRITICAL: only export PX4_SIM_SPEED_FACTOR for non-realtime runs. Setting it at
# all makes PX4's rcS (px4-rc.gzsim) call the gz set_physics service, which sends
# real_time_factor but leaves max_step_size unset, so protobuf defaults it to 0,
# overwriting the world's 0.004 step. The zero step makes physics integration blow
# up: after arming the vehicle climbs away uncontrollably (the altitude "runaway").
# At the default speed=1.0 we omit it and the world's own real-time settings apply.
# (verified: omitting it gives a clean 3 m offboard hold.)
if [ "$SIM_SPEED" != "1.0" ]; then
  export PX4_SIM_SPEED_FACTOR="$SIM_SPEED"
fi

export GZ_SIM_RESOURCE_PATH="$GZ_PATHS"
export PX4_GZ_WORLDS="$PX4_GZ_WORLDS_DIR"
export PX4_GZ_PLUGINS="$PX4_GZ_PLUGINS_DIR"
export PX4_GZ_SERVER_CONFIG="$PX4_GZ_SERVER_CFG"
export GZ_SIM_SERVER_CONFIG_PATH="$PX4_GZ_SERVER_CFG"
export GZ_SIM_SYSTEM_PLUGIN_PATH="$PX4_GZ_PLUGINS_DIR"
export LD_LIBRARY_PATH="$PX4_GZ_PLUGINS_DIR:${LD_LIBRARY_PATH}"

# Applied at STARTUP (reliable) rather than via gcs_heartbeat over lossy UDP.
# Arming/EKF reliability: allow GPS fusion without strict SITL checks, arm w/o GPS.
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

echo "[sim_full] Starting PX4 (it starts Gazebo in lockstep) world='$SIM_WORLD' model='$SIM_MODEL'"

cd "$PX4_BUILD"
# Boot from stock airframe defaults every time (determinism): clear any params
# persisted by a prior run so flight behaviour never drifts between launches.
rm -f rootfs/parameters*.bson 2>/dev/null || true
exec env PX4_GZ_WORLD="$SIM_WORLD" PX4_SIM_MODEL="gz_${SIM_MODEL}" ./bin/px4
