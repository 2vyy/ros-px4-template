"""Name → behavior/guard registries (populated by importing behaviors+guards)."""

from __future__ import annotations

from collections.abc import Callable

from ros_px4_template_core.lib.mission.commands import BehaviorResult
from ros_px4_template_core.lib.mission.types import Inputs

Behavior = Callable[[dict, Inputs, dict], BehaviorResult]
Guard = Callable[[Inputs, dict, dict], bool]

_BEHAVIORS: dict[str, Behavior] = {}
_GUARDS: dict[str, Guard] = {}


def behavior(name: str) -> Callable[[Behavior], Behavior]:
    def deco(fn: Behavior) -> Behavior:
        _BEHAVIORS[name] = fn
        return fn

    return deco


def guard(name: str) -> Callable[[Guard], Guard]:
    def deco(fn: Guard) -> Guard:
        _GUARDS[name] = fn
        return fn

    return deco


def get_behavior(name: str) -> Behavior:
    if name not in _BEHAVIORS:
        raise KeyError(f"unknown behavior '{name}' (known: {sorted(_BEHAVIORS)})")
    return _BEHAVIORS[name]


def get_guard(name: str) -> Guard:
    if name not in _GUARDS:
        raise KeyError(f"unknown guard '{name}' (known: {sorted(_GUARDS)})")
    return _GUARDS[name]


def known_behaviors() -> set[str]:
    return set(_BEHAVIORS)


def known_guards() -> set[str]:
    return set(_GUARDS)
