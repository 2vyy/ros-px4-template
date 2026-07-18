#!/usr/bin/env python3
"""Manage tests/capabilities.toml capability registry."""

from __future__ import annotations

import tomllib
from pathlib import Path

import typer

app = typer.Typer()
REGISTRY = Path(__file__).resolve().parents[1] / "tests" / "capabilities.toml"


def _load(registry: Path | None = None) -> dict:
    path = registry or REGISTRY
    if not path.is_file():
        return {"capabilities": {}}
    return tomllib.loads(path.read_text(encoding="utf-8"))


def _validated_data() -> dict:
    """Load the registry or stop before consuming an invalid claim graph."""
    from check_capabilities import validate_registry

    try:
        if not REGISTRY.is_file():
            raise FileNotFoundError(f"{REGISTRY} missing")
        data = _load()
    except (OSError, tomllib.TOMLDecodeError) as error:
        typer.echo(f"REGISTRY INVALID: {error} (run `just check`)", err=True)
        raise typer.Exit(2) from None
    errors = validate_registry(data)
    if errors:
        for error in errors:
            typer.echo(f"  [FAIL] {error}", err=True)
        typer.echo("REGISTRY INVALID: run `just check`", err=True)
        raise typer.Exit(2)
    return data


@app.command()
def show() -> None:
    """Print each claim's derived rung. Rungs are never stored."""
    from cap_evidence import (
        EVIDENCE_ROOT,
        load_records,
        real_evidence_committed,
    )
    from cap_status import (
        derive_all,
        display,
        evidence_age,
        real_artifacts_ok,
        real_changed_since,
        real_mission_ok,
    )

    data = _validated_data()
    capabilities = data.get("capabilities", {})
    records = {
        name: load_records(
            EVIDENCE_ROOT,
            name,
            usable=real_evidence_committed,
        )
        for name in capabilities
    }
    infos = derive_all(
        data,
        records,
        real_changed_since,
        real_artifacts_ok,
        real_mission_ok,
    )
    flown = 0
    for name, info in infos.items():
        age = ""
        if info.evidence:
            age = (
                f"  evidence {evidence_age(info.evidence)} old @ {info.evidence.get('commit', '?')}"
            )
        note = f"  ({info.reason})" if info.reason and info.rung != "sim-flown" else ""
        typer.echo(f"{name:<22} {display(info):<32}{age}{note}")
        flown += info.rung == "sim-flown"
    typer.echo(f"CLAIMS: {flown}/{len(infos)} sim-flown (derived, not stored)")


@app.command()
def record(claim: str) -> None:
    """File PASS evidence for CLAIM from its latest scenario report."""
    import json
    import subprocess

    from cap_evidence import (
        EVIDENCE_ROOT,
        REGISTRY_PATH,
        build_record,
        changed_registry_claims,
        dirty_flight_paths,
        git_state_mtimes,
        report_is_fresh,
        write_record,
    )

    data = _validated_data()
    entry = data.get("capabilities", {}).get(claim)
    if entry is None or "scenario_file" not in entry:
        typer.echo(f"NO SUCH LEAF CLAIM: {claim} (see just cap show)", err=True)
        raise typer.Exit(2)
    if "sim" not in entry.get("platforms", []):
        typer.echo(f"SIM NOT DECLARED: {claim} cannot record sim evidence", err=True)
        raise typer.Exit(3)

    stem = entry["scenario_file"].removesuffix(".py")
    report_path = Path("logs") / f"scenario_{stem}.json"
    if not report_path.exists():
        typer.echo(
            f"NO REPORT: run `just scenario {stem}` first ({report_path} missing)",
            err=True,
        )
        raise typer.Exit(3)
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        typer.echo(
            f"INVALID REPORT: run `just scenario {stem}` again ({report_path})",
            err=True,
        )
        raise typer.Exit(3) from None
    if report.get("scenario") != stem:
        typer.echo(
            f"REPORT SCENARIO MISMATCH: expected {stem}, "
            f"got {report.get('scenario')!r}; run the scenario again",
            err=True,
        )
        raise typer.Exit(3)
    if not report.get("passed"):
        typer.echo(
            f"REPORT IS A FAIL: evidence records PASSes only ({report_path})",
            err=True,
        )
        raise typer.Exit(3)

    status = subprocess.run(
        ["git", "status", "--porcelain"],
        capture_output=True,
        text=True,
    )
    if status.returncode != 0:
        typer.echo("GIT STATUS FAILED: cannot prove a clean recording base", err=True)
        raise typer.Exit(3)

    registry_claims: list[str] | None = None
    if REGISTRY_PATH in status.stdout:
        previous = subprocess.run(
            ["git", "show", f"HEAD:{REGISTRY_PATH}"],
            capture_output=True,
            text=True,
        )
        if previous.returncode == 0:
            try:
                registry_claims = changed_registry_claims(
                    previous.stdout,
                    REGISTRY.read_text(encoding="utf-8"),
                )
            except (OSError, ValueError):
                pass
    dirty = dirty_flight_paths(
        status.stdout,
        entry["scenario_file"],
        claim,
        registry_claims,
    )
    if dirty:
        typer.echo(
            "DIRTY TREE: commit flight-relevant changes first: " + ", ".join(dirty[:5]),
            err=True,
        )
        raise typer.Exit(3)

    revision = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        capture_output=True,
        text=True,
    )
    commit = revision.stdout.strip()
    if revision.returncode != 0 or not commit:
        typer.echo("GIT REVISION FAILED: cannot identify evidence commit", err=True)
        raise typer.Exit(3)
    head_timestamp = subprocess.run(
        ["git", "show", "-s", "--format=%ct", "HEAD"],
        capture_output=True,
        text=True,
    )
    try:
        commit_time = float(head_timestamp.stdout.strip())
        report_mtime = report_path.stat().st_mtime
        revision_mtimes = (commit_time, *git_state_mtimes())
    except (OSError, RuntimeError, ValueError):
        typer.echo("REPORT FRESHNESS UNKNOWN: run the scenario again", err=True)
        raise typer.Exit(3) from None
    if head_timestamp.returncode != 0 or not report_is_fresh(report_mtime, *revision_mtimes):
        typer.echo(
            f"STALE REPORT: run `just scenario {stem}` after the current commit",
            err=True,
        )
        raise typer.Exit(3)
    conditions = {
        "world": entry.get("sim_world", "default"),
        "model": entry.get("sim_model", "x500"),
        "vision": entry.get("sim_vision", "none"),
    }
    evidence = build_record(claim, "sim", commit, report, conditions)
    output = write_record(evidence, EVIDENCE_ROOT)
    typer.echo(f"RECORDED {claim} sim PASS @ {commit} -> {output} (commit the file)")


@app.command()
def plan(
    claim: str = typer.Argument("", help="Scope to this claim's requires closure"),
) -> None:
    """Print the dependency-first frontier. Exit zero means complete."""
    from cap_evidence import (
        EVIDENCE_ROOT,
        load_records,
        real_evidence_committed,
    )
    from cap_plan import format_plan
    from cap_status import (
        derive_all,
        real_artifacts_ok,
        real_changed_since,
        real_mission_ok,
    )

    data = _validated_data()
    capabilities = data.get("capabilities", {})
    if claim and claim not in capabilities:
        typer.echo(f"NO SUCH CLAIM: {claim}", err=True)
        raise typer.Exit(2)
    records = {
        name: load_records(
            EVIDENCE_ROOT,
            name,
            usable=real_evidence_committed,
        )
        for name in capabilities
    }
    infos = derive_all(
        data,
        records,
        real_changed_since,
        real_artifacts_ok,
        real_mission_ok,
    )
    text, complete = format_plan(data, infos, claim or None)
    typer.echo(text)
    raise typer.Exit(0 if complete else 1)


def scenarios_for_platform(platform: str = "sim", registry: Path = REGISTRY) -> list[str]:
    """Return scenario names (without .py) for the given platform, in TOML order."""
    data = _load(registry)
    result = []
    for cap in data.get("capabilities", {}).values():
        if platform in cap.get("platforms", []) and cap.get("scenario_file"):
            result.append(cap["scenario_file"].removesuffix(".py"))
    return result


def claim_for_scenario(data: dict, scenario: str) -> str | None:
    for name, entry in data.get("capabilities", {}).items():
        if entry.get("scenario_file", "").removesuffix(".py") == scenario:
            return name
    return None


def e2e_roster(
    data: dict,
    artifacts_ok,
    platform: str = "sim",
) -> tuple[list[dict], list[str]]:
    """Topo-ordered e2e configs; leaves below `simulated` are excluded (named).

    Same config shape as scenario_sim_configs; composites never enter the
    roster (nothing to fly)."""
    from cap_plan import topo_order

    caps = data.get("capabilities", {})
    configs: list[dict] = []
    excluded: list[str] = []
    for name in topo_order(data):
        entry = caps[name]
        if platform not in entry.get("platforms", []) or not entry.get("scenario_file"):
            continue
        ok, _why = artifacts_ok(entry)
        if not ok:
            excluded.append(name)
            continue
        configs.append(
            {
                "scenario": entry["scenario_file"].removesuffix(".py"),
                "vision": entry.get("sim_vision", "none"),
                "overlay": entry.get("sim_overlay", "auto_arm"),
                "model": entry.get("sim_model", "x500"),
                "world": entry.get("sim_world", "default"),
            }
        )
    return configs, excluded


def scenario_sim_configs(platform: str = "sim", registry: Path = REGISTRY) -> list[dict]:
    """Return per-scenario sim configs for the platform, in TOML order.

    Each entry is ``{"scenario", "vision", "overlay", "model", "world"}``.
    The fields come from ``sim_vision``/``sim_overlay``/``sim_model``/``sim_world``
    in the registry, letting the e2e harness launch an isolated sim per config so
    hold scenarios and path scenarios don't share (and corrupt) one sim, and so a
    perception scenario can boot a camera model + marker world while the synthetic
    scenarios stay on the default model/world. Defaults keep older registries
    working: vision="none", overlay="auto_arm", model="x500", world="default".
    """
    data = _load(registry)
    result = []
    for cap in data.get("capabilities", {}).values():
        if platform in cap.get("platforms", []) and cap.get("scenario_file"):
            result.append(
                {
                    "scenario": cap["scenario_file"].removesuffix(".py"),
                    "vision": cap.get("sim_vision", "none"),
                    "overlay": cap.get("sim_overlay", "auto_arm"),
                    "model": cap.get("sim_model", "x500"),
                    "world": cap.get("sim_world", "default"),
                }
            )
    return result


if __name__ == "__main__":
    app()
