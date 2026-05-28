"""Canonical event names used by StructuredLogger.event() and mission_runtime.

Centralising these prevents typos, lets tools (status, log-events, e2e-report)
discover the full taxonomy, and gives agents a single import to grep.
"""

from __future__ import annotations

# Mission phase transitions and milestones (emitted by mission_runtime).
PHASE_CHANGE = "PHASE_CHANGE"
WAYPOINT_REACHED = "WAYPOINT_REACHED"
MISSION_DONE = "MISSION_DONE"
MARKER_ACQUIRED = "MARKER_ACQUIRED"
MARKER_LOST = "MARKER_LOST"

# Arming / mode handshake (emitted by offboard_controller).
ARM_COMMAND_SENT = "ARM_COMMAND_SENT"
ARM_ACK_OK = "ARM_ACK_OK"
ARM_ACK_DENIED = "ARM_ACK_DENIED"
OFFBOARD_MODE_COMMAND = "OFFBOARD_MODE_COMMAND"

ALL_EVENTS: frozenset[str] = frozenset(
    {
        PHASE_CHANGE,
        WAYPOINT_REACHED,
        MISSION_DONE,
        MARKER_ACQUIRED,
        MARKER_LOST,
        ARM_COMMAND_SENT,
        ARM_ACK_OK,
        ARM_ACK_DENIED,
        OFFBOARD_MODE_COMMAND,
    }
)
