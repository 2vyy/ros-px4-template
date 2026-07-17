#!/usr/bin/env python3
"""FORM validation for tests/capabilities.toml.

Runs inside ``just check``. Rejects malformed claims: unknown or cyclic
``requires``, empty-requires composites, bad types, unknown platforms, and
the retired stored-status fields. Artifact existence is deliberately not
checked here: missing artifacts hold a claim at ``declared`` in cap_status,
so a claim can be added before its scenario exists.
"""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path

KNOWN_PLATFORMS = ("sim", "hw")
REGISTRY = Path(__file__).resolve().parents[1] / "tests" / "capabilities.toml"
_STR_FIELDS = (
    "description",
    "scenario_file",
    "mission",
    "source",
    "sim_vision",
    "sim_overlay",
    "sim_model",
    "sim_world",
)


def _find_cycle(caps: dict) -> list[str] | None:
    state: dict[str, int] = {}  # 0 visiting, 1 done
    stack: list[str] = []

    def visit(node: str) -> list[str] | None:
        if state.get(node) == 0:
            start = stack.index(node)
            return [*stack[start:], node]
        if state.get(node) == 1 or node not in caps:
            return None
        state[node] = 0
        stack.append(node)
        entry = caps[node]
        raw_requires = entry.get("requires", []) if isinstance(entry, dict) else []
        requires = (
            raw_requires
            if isinstance(raw_requires, list)
            and all(isinstance(dependency, str) for dependency in raw_requires)
            else []
        )
        for dependency in requires:
            if isinstance(dependency, str) and (cycle := visit(dependency)):
                return cycle
        stack.pop()
        state[node] = 1
        return None

    for name in caps:
        if cycle := visit(name):
            return cycle
    return None


def validate_registry(data: dict) -> list[str]:
    """Return registry form errors. An empty list means the registry is valid."""
    errors: list[str] = []
    caps = data.get("capabilities", {})
    if not isinstance(caps, dict):
        return ["'capabilities' must be a table of claim entries"]

    for name, entry in caps.items():
        if not isinstance(entry, dict):
            errors.append(f"{name}: claim entry must be a table")
            continue

        for legacy in ("status", "last_verified"):
            if legacy in entry:
                errors.append(
                    f"{name}: field '{legacy}' is retired -- rungs are derived "
                    "(delete it; see docs/CLAIMS.md)"
                )

        if not isinstance(entry.get("description", ""), str) or not entry.get("description"):
            errors.append(f"{name}: 'description' (non-empty string) is required")

        requires = entry.get("requires", [])
        if not (isinstance(requires, list) and all(isinstance(dep, str) for dep in requires)):
            errors.append(f"{name}: 'requires' must be a list of claim ids")
            requires = []
        for dependency in requires:
            if dependency not in caps:
                errors.append(
                    f"{name}: requires unknown claim '{dependency}' (add it or fix the id)"
                )

        is_leaf = "scenario_file" in entry
        if not is_leaf and not requires:
            errors.append(
                f"{name}: composite claim (no scenario_file) must have non-empty 'requires'"
            )
        platforms = entry.get("platforms")
        if is_leaf and not (isinstance(platforms, list) and platforms):
            errors.append(f"{name}: leaf claim needs non-empty 'platforms'")
        elif "platforms" in entry:
            if not isinstance(platforms, list):
                errors.append(f"{name}: 'platforms' must be a list")
            else:
                for platform in platforms:
                    if platform not in KNOWN_PLATFORMS:
                        errors.append(
                            f"{name}: unknown platform '{platform}' (known: {KNOWN_PLATFORMS})"
                        )

        for field in _STR_FIELDS:
            if field in entry and not isinstance(entry[field], str):
                errors.append(f"{name}: '{field}' must be a string")
        if "params" in entry and not isinstance(entry["params"], dict):
            errors.append(f"{name}: 'params' must be a table")

    if cycle := _find_cycle(caps):
        errors.append(
            f"{cycle[0]}: requires graph has a cycle ({' -> '.join(cycle)}) "
            "(remove a requires edge so claims form a DAG)"
        )
    return errors


def main() -> None:
    """Validate the repository registry and print a stable verdict."""
    try:
        data = tomllib.loads(REGISTRY.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as error:
        data = {}
        errors = [f"invalid TOML in {REGISTRY.name}: {error}"]
    except OSError as error:
        data = {}
        errors = [f"cannot read {REGISTRY}: {error}"]
    else:
        errors = validate_registry(data)

    for error in errors:
        print(f"  [FAIL] {error}", file=sys.stderr)
    caps = data.get("capabilities", {})
    claim_count = len(caps) if isinstance(caps, dict) else 0
    if errors:
        print(
            f"REGISTRY INVALID: {len(errors)} error(s) in {REGISTRY.name}",
            file=sys.stderr,
        )
        raise SystemExit(1)
    print(f"REGISTRY OK: {claim_count} claims, DAG valid")


if __name__ == "__main__":
    main()
