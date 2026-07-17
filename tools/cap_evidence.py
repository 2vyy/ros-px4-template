#!/usr/bin/env python3
"""Committed PASS-evidence ledger for the claims ladder.

One small JSON record per passing run lives under ``tests/evidence/<claim>/``.
Failures stay in logs; the ledger measures proven capability. See
``docs/CLAIMS.md``.
"""

from __future__ import annotations

import json
import sys
import tomllib
from datetime import UTC, datetime
from pathlib import Path

FLIGHT_PATHS: tuple[str, ...] = ("src/", "sim/", "config/")
REGISTRY_PATH = "tests/capabilities.toml"
EVIDENCE_ROOT = Path(__file__).resolve().parents[1] / "tests" / "evidence"


def registry_marker(claim: str) -> str:
    """Return the synthetic changed-path marker for one registry entry."""
    return f"{REGISTRY_PATH}#{claim}"


def flight_relevant(
    paths: list[str], scenario_file: str | None, claim: str | None = None
) -> list[str]:
    """Return paths that can change one claim's flight result."""
    scenario = f"tests/scenarios/{scenario_file}" if scenario_file else None
    own_registry_entry = registry_marker(claim) if claim else None
    return [
        path
        for path in paths
        if path.startswith(FLIGHT_PATHS)
        or path == scenario
        or path == own_registry_entry
        or (path == f"{REGISTRY_PATH}#*" and claim is not None)
    ]


def changed_registry_claims(old_text: str, new_text: str) -> list[str]:
    """Return claim ids whose TOML entry differs between two registry texts."""
    old_caps = tomllib.loads(old_text).get("capabilities", {})
    new_caps = tomllib.loads(new_text).get("capabilities", {})
    names = dict.fromkeys([*old_caps, *new_caps])
    return [name for name in names if old_caps.get(name) != new_caps.get(name)]


def build_record(
    claim: str,
    platform: str,
    commit: str,
    report: dict,
    conditions: dict,
) -> dict:
    """Build the stable evidence schema from a passing scenario report."""
    if not report.get("passed"):
        raise ValueError("evidence records PASS reports only")
    return {
        "claim": claim,
        "platform": platform,
        "commit": commit,
        "run_id": datetime.now(UTC).strftime("%Y%m%d_%H%M%S"),
        "verdict": "PASS",
        "elapsed_s": report.get("elapsed_s", 0.0),
        "detail": report.get("detail", {}),
        "conditions": conditions,
        "grade": None,
    }


def write_record(record: dict, root: Path = EVIDENCE_ROOT, keep: int = 3) -> Path:
    """Write one record and retain the newest ``keep`` files per platform."""
    directory = root / record["claim"]
    directory.mkdir(parents=True, exist_ok=True)
    output = directory / f"{record['run_id']}_{record['platform']}.json"
    output.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    same_platform = sorted(directory.glob(f"*_{record['platform']}.json"))
    for old in same_platform[:-keep]:
        old.unlink()
    return output


def load_records(root: Path, claim: str) -> list[dict]:
    """Load one claim's records newest first, warning on unreadable files."""
    directory = root / claim
    if not directory.is_dir():
        return []
    records: list[dict] = []
    for path in sorted(directory.glob("*.json"), reverse=True):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(record, dict):
                raise ValueError("evidence record must be a JSON object")
            records.append(record)
        except (json.JSONDecodeError, OSError, ValueError):
            print(
                f"[cap_evidence] WARN: unreadable evidence skipped: {path}",
                file=sys.stderr,
            )
    return records
