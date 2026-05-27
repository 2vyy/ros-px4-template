#!/usr/bin/env bash
# End-to-end sim smoke test (run inside distrobox: tools/e2e_sim_test.sh)
set -eo pipefail
cd "$(dirname "$0")/.."
source /opt/ros/jazzy/setup.bash
source install/setup.bash
export GZ_IP=127.0.0.1

just sim-stop 2>/dev/null || true
pkill -f 'gz sim' 2>/dev/null || true
sleep 5

LOG=logs/e2e_launch.log
rm -f "$LOG"
# GUI mode is more reliable in distrobox+Sway; headless skips gz GUI only
timeout 600 ros2 launch sim/launch/sim_full.launch.py headless:=true >>"$LOG" 2>&1 &
LPID=$!
echo "launch pid $LPID"
echo "Waiting 45s for PX4 + EKF + clock..."
sleep 45

for i in $(seq 1 60); do
  if timeout 8 ros2 topic echo /fmu/out/vehicle_local_position --once --qos-reliability best_effort --qos-durability transient_local 2>/dev/null | grep -q 'z:'; then
    echo "POSITION_OK at iter $i"
    just check-topics
    just scenario 01_arm_takeoff
    RC=$?
    kill $LPID 2>/dev/null || true
    sleep 2
    just sim-stop 2>/dev/null || true
    exit $RC
  fi
  sleep 5
done

echo "FAIL — no /fmu/out/vehicle_local_position data"
grep -E "ERROR|Timed out|gz_sim|clock" "$LOG" | tail -25
kill $LPID 2>/dev/null || true
just sim-stop 2>/dev/null || true
exit 1
