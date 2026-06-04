"""Canonical event names used by StructuredLogger.event() and mission_runtime.

Centralising these prevents typos and lets tools (status, log-events, e2e-report)
discover the full taxonomy.
"""

from __future__ import annotations

# Mission phase transitions and milestones (emitted by mission_runtime).
PHASE_CHANGE = "PHASE_CHANGE"
WAYPOINT_REACHED = "WAYPOINT_REACHED"
MISSION_DONE = "MISSION_DONE"
MARKER_ACQUIRED = "MARKER_ACQUIRED"
MARKER_LOST = "MARKER_LOST"
MARKER_HOVER_START = "MARKER_HOVER_START"
TARGET_POSE_STALE = "TARGET_POSE_STALE"

# Arming / mode handshake (emitted by offboard_controller).
ARM_COMMAND_SENT = "ARM_COMMAND_SENT"
ARM_ACK_OK = "ARM_ACK_OK"
ARM_ACK_DENIED = "ARM_ACK_DENIED"
OFFBOARD_MODE_COMMAND = "OFFBOARD_MODE_COMMAND"
TAKEOFF_COMMAND_SENT = "TAKEOFF_COMMAND_SENT"
