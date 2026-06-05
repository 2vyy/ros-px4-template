"""Pure FSM engine: tiered, deterministic, single-transition-per-tick, logged."""

from __future__ import annotations

from dataclasses import dataclass, field

from ros_px4_template_core.lib.mission.commands import Command
from ros_px4_template_core.lib.mission.registry import get_behavior, get_guard
from ros_px4_template_core.lib.mission.types import Inputs, Mission, TransitionDef


@dataclass
class MissionContext:
    state: str
    scratch: dict[str, dict] = field(default_factory=dict)
    events: list[dict] = field(default_factory=list)


def _first_fired(
    edges: tuple[TransitionDef, ...], inputs: Inputs, signals: dict
) -> TransitionDef | None:
    for edge in edges:
        if get_guard(edge.guard)(inputs, signals, edge.params):
            return edge
    return None


def _run(ctx: MissionContext, mission: Mission, inputs: Inputs) -> tuple[Command, dict]:
    state = mission.states[ctx.state]
    scratch = ctx.scratch.setdefault(ctx.state, {})
    result = get_behavior(state.behavior)(scratch, inputs, state.params)
    return result.command, result.signals


def tick(ctx: MissionContext, mission: Mission, inputs: Inputs) -> Command:
    """Advance the FSM one step over an immutable snapshot; return one command."""
    command, signals = _run(ctx, mission, inputs)

    fired = _first_fired(mission.safety, inputs, signals)
    tier = "safety"
    if fired is None and ctx.state not in mission.terminal:
        outgoing = tuple(t for t in mission.transitions if t.src == ctx.state)
        fired = _first_fired(outgoing, inputs, signals)
        tier = "mission"

    if fired is not None:
        ctx.events.append(
            {
                "event": "TRANSITION",
                "from": ctx.state,
                "to": fired.dst,
                "guard": fired.guard,
                "tier": tier,
                "trigger": {
                    "params": dict(fired.params),
                    "pose_enu": inputs.pose_enu,
                    "armed": inputs.armed,
                    "estimate_ok": inputs.estimate_ok,
                    "detection_ids": [d.id for d in inputs.detections],
                    "now": inputs.now,
                },
            }
        )
        ctx.scratch.pop(ctx.state, None)
        ctx.state = fired.dst
        ctx.scratch.pop(ctx.state, None)  # fresh entry
        command, _ = _run(ctx, mission, inputs)

    return command
