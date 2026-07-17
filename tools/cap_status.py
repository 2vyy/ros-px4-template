#!/usr/bin/env python3
"""Derive claim rungs from artifacts and committed evidence. Never stored.

``declared`` means the registry entry is valid but an artifact is missing or
its mission dry-run fails. ``simulated`` means every declared artifact resolves.
``sim-flown`` requires a current simulated PASS record. Evidence becomes
``sim-flown-stale`` when its commit is gone or a flight-relevant path changed.
Composite claims take the minimum rung of their requirements.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from cap_evidence import (
    REGISTRY_PATH,
    changed_registry_claims,
    flight_relevant,
    registry_marker,
)

RUNG_ORDER = ("declared", "simulated", "sim-flown-stale", "sim-flown")
ROOT = Path(__file__).resolve().parents[1]


@dataclass
class RungInfo:
    rung: str
    reason: str = ""
    evidence: dict | None = None


def display(info: RungInfo) -> str:
    """Return the stable human display form for a derived rung."""
    if info.rung == "sim-flown-stale":
        commit = (info.evidence or {}).get("commit", "?")
        return f"sim-flown (stale, since {commit})"
    return info.rung


def evidence_age(record: dict, now: datetime | None = None) -> str:
    """Return a compact UTC age for a ledger record's run id."""
    try:
        created = datetime.strptime(record["run_id"], "%Y%m%d_%H%M%S").replace(tzinfo=UTC)
    except (KeyError, TypeError, ValueError):
        return "?"
    elapsed = max(0, int(((now or datetime.now(UTC)) - created).total_seconds()))
    if elapsed >= 86_400:
        return f"{elapsed // 86_400}d"
    if elapsed >= 3_600:
        return f"{elapsed // 3_600}h"
    if elapsed >= 60:
        return f"{elapsed // 60}m"
    return f"{elapsed}s"


def _leaf_rung(
    name: str,
    entry: dict,
    records: list[dict],
    changed_since: Callable[[str], list[str] | None],
    artifacts_ok: Callable[[dict], tuple[bool, str]],
    mission_ok: Callable[[str], tuple[bool, str]],
) -> RungInfo:
    ok, reason = artifacts_ok(entry)
    if ok and entry.get("mission"):
        ok, reason = mission_ok(entry["mission"])
    if not ok:
        return RungInfo("declared", reason=reason)

    passes = [
        record
        for record in records
        if record.get("verdict") == "PASS" and record.get("platform") == "sim"
    ]
    if not passes:
        return RungInfo("simulated")

    evidence = passes[0]
    commit = evidence.get("commit")
    if not isinstance(commit, str) or not commit:
        return RungInfo("sim-flown-stale", reason="commit_unknown", evidence=evidence)
    changed = changed_since(commit)
    if changed is None:
        return RungInfo("sim-flown-stale", reason="commit_unknown", evidence=evidence)
    hits = flight_relevant(changed, entry.get("scenario_file"), name)
    if hits:
        return RungInfo(
            "sim-flown-stale",
            reason=f"changed: {', '.join(hits[:3])}",
            evidence=evidence,
        )
    return RungInfo("sim-flown", evidence=evidence)


def derive_all(
    data: dict,
    records: dict[str, list[dict]],
    changed_since: Callable[[str], list[str] | None],
    artifacts_ok: Callable[[dict], tuple[bool, str]],
    mission_ok: Callable[[str], tuple[bool, str]],
) -> dict[str, RungInfo]:
    """Derive every leaf and composite rung from injected facts."""
    capabilities = data.get("capabilities", {})
    derived: dict[str, RungInfo] = {}

    def rung_of(name: str) -> RungInfo:
        if name in derived:
            return derived[name]
        entry = capabilities[name]
        if "scenario_file" in entry:
            info = _leaf_rung(
                name,
                entry,
                records.get(name, []),
                changed_since,
                artifacts_ok,
                mission_ok,
            )
        else:
            children = [
                rung_of(dependency)
                for dependency in entry.get("requires", [])
                if dependency in capabilities
            ]
            if not children:
                info = RungInfo("declared", reason="requires unknown claims (run just check)")
            else:
                lowest = min(children, key=lambda child: RUNG_ORDER.index(child.rung))
                info = RungInfo(
                    lowest.rung,
                    reason=f"composite: min of requires; {lowest.reason}".rstrip("; "),
                    evidence=lowest.evidence,
                )
        derived[name] = info
        return info

    for name in capabilities:
        rung_of(name)
    return derived


def real_changed_since(commit: str) -> list[str] | None:
    """Return paths changed from an evidence commit to HEAD.

    Registry changes are expanded into synthetic per-claim path markers so a
    claim becomes stale only when its own TOML entry changed.
    """
    result = subprocess.run(
        ["git", "diff", "--name-only", f"{commit}..HEAD"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    paths = [line for line in result.stdout.splitlines() if line]
    if REGISTRY_PATH not in paths:
        return paths

    previous = subprocess.run(
        ["git", "show", f"{commit}:{REGISTRY_PATH}"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )
    if previous.returncode != 0:
        paths.append(f"{REGISTRY_PATH}#*")
        return paths
    try:
        current = (ROOT / REGISTRY_PATH).read_text(encoding="utf-8")
        paths.extend(
            registry_marker(claim) for claim in changed_registry_claims(previous.stdout, current)
        )
    except (OSError, ValueError):
        paths.append(f"{REGISTRY_PATH}#*")
    return paths


def real_artifacts_ok(entry: dict) -> tuple[bool, str]:
    """Check that a leaf's scenario and declared simulation artifacts resolve."""
    missing: list[str] = []
    scenario = entry.get("scenario_file", "")
    if not (ROOT / "tests" / "scenarios" / scenario).is_file():
        missing.append(f"scenario missing: tests/scenarios/{scenario}")

    overlay = entry.get("sim_overlay", "auto_arm")
    if not (ROOT / "config" / "params" / "overlays" / f"{overlay}.yaml").is_file():
        missing.append(f"overlay missing: {overlay}")

    world = entry.get("sim_world", "default")
    if not (ROOT / "sim" / "worlds" / f"{world}.sdf").is_file():
        missing.append(f"world missing: {world}")

    model = entry.get("sim_model", "x500")
    if model != "x500" and not (ROOT / "sim" / "models" / model).is_dir():
        missing.append(f"model missing: {model}")

    vision = entry.get("sim_vision", "none")
    if vision not in ("none", "aruco"):
        missing.append(f"unknown vision: {vision}")

    mission = entry.get("mission")
    if mission and not (ROOT / "config" / "missions" / f"{mission}.yaml").is_file():
        missing.append(f"mission missing: {mission}")
    return not missing, "; ".join(missing)


def real_mission_ok(name: str) -> tuple[bool, str]:
    """Run the mission graph simulator without booting Gazebo."""
    result = subprocess.run(
        ["uv", "run", "python", "tools/mission_cli.py", "sim", name],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        return True, ""
    return False, f"mission sim failing: {name} (run: just mission sim {name})"
