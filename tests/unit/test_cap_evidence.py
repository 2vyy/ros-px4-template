"""Committed claims evidence ledger tests."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

import cap_evidence
import capabilities
from cap_evidence import (
    build_record,
    changed_registry_claims,
    dirty_flight_paths,
    flight_relevant,
    git_state_mtimes,
    load_records,
    real_evidence_committed,
    report_is_fresh,
    write_record,
)

_REPORT = {
    "scenario": "08_precision_land",
    "passed": True,
    "elapsed_s": 141.2,
    "detail": {"xy_err": 0.06},
}
_ARM_REPORT = {**_REPORT, "scenario": "01_arm_takeoff"}


def test_build_record_shape() -> None:
    rec = build_record(
        "precision_land",
        "sim",
        "5c1124f",
        _REPORT,
        {"world": "default", "model": "x500", "vision": "aruco"},
    )
    assert set(rec) == {
        "claim",
        "platform",
        "commit",
        "run_id",
        "verdict",
        "elapsed_s",
        "detail",
        "conditions",
        "grade",
    }
    assert rec["verdict"] == "PASS"
    assert rec["grade"] is None
    assert rec["detail"] == {"xy_err": 0.06}


def test_build_record_rejects_failed_report() -> None:
    report = {**_REPORT, "passed": False}
    with pytest.raises(ValueError, match="PASS"):
        build_record("precision_land", "sim", "5c1124f", report, {})


def test_write_prunes_to_keep(tmp_path: Path) -> None:
    for i in range(5):
        rec = build_record("c", "sim", f"c{i}", _REPORT, {})
        rec["run_id"] = f"2026071{i}_000000"  # distinct filenames
        write_record(rec, tmp_path, keep=3)
    files = sorted((tmp_path / "c").glob("*.json"))
    assert len(files) == 3


def test_write_prunes_each_platform_independently(tmp_path: Path) -> None:
    for platform in ("sim", "hw"):
        for i in range(4):
            rec = build_record("c", platform, f"c{i}", _REPORT, {})
            rec["run_id"] = f"2026071{i}_000000"
            write_record(rec, tmp_path, keep=3)
    assert len(list((tmp_path / "c").glob("*_sim.json"))) == 3
    assert len(list((tmp_path / "c").glob("*_hw.json"))) == 3


def test_load_records_newest_first_and_skips_corrupt(tmp_path: Path, capsys) -> None:
    directory = tmp_path / "c"
    directory.mkdir()
    (directory / "20260101_000000_sim.json").write_text(json.dumps({"commit": "old"}))
    (directory / "20260201_000000_sim.json").write_text(json.dumps({"commit": "new"}))
    corrupt = directory / "20260301_000000_sim.json"
    corrupt.write_text("{not json")

    records = load_records(tmp_path, "c")

    assert [record["commit"] for record in records] == ["new", "old"]
    assert str(corrupt) in capsys.readouterr().err


def test_load_records_skips_uncommitted_or_modified(tmp_path: Path, capsys) -> None:
    directory = tmp_path / "c"
    directory.mkdir()
    committed = directory / "20260101_000000_sim.json"
    dirty = directory / "20260201_000000_sim.json"
    committed.write_text(json.dumps({"commit": "committed"}))
    dirty.write_text(json.dumps({"commit": "dirty"}))

    records = load_records(
        tmp_path,
        "c",
        usable=lambda path: path == committed,
    )

    assert [record["commit"] for record in records] == ["committed"]
    warning = capsys.readouterr().err
    assert "uncommitted evidence skipped" in warning
    assert str(dirty) in warning


def test_real_evidence_requires_tracked_unchanged_head(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = {"tracked": False, "clean": True}

    def fake_run(args: list[str], **kwargs: object) -> SimpleNamespace:
        if args[:3] == ["git", "ls-files", "--error-unmatch"]:
            return SimpleNamespace(returncode=0 if state["tracked"] else 1)
        if args[:3] == ["git", "diff", "--quiet"]:
            return SimpleNamespace(returncode=0 if state["clean"] else 1)
        raise AssertionError(args)

    monkeypatch.setattr(cap_evidence.subprocess, "run", fake_run)
    path = cap_evidence.ROOT / "tests" / "evidence" / "c" / "record.json"

    assert not real_evidence_committed(path)
    state["tracked"] = True
    state["clean"] = False
    assert not real_evidence_committed(path)
    state["clean"] = True
    assert real_evidence_committed(path)


def test_flight_relevant_filters() -> None:
    changed = [
        "src/core/x.py",
        "docs/README.md",
        "tests/scenarios/08_precision_land.py",
        "tests/scenarios/01_arm_takeoff.py",
        "plans/074.md",
    ]
    hit = flight_relevant(changed, "08_precision_land.py")
    assert hit == ["src/core/x.py", "tests/scenarios/08_precision_land.py"]


def test_flight_relevant_includes_own_registry_entry_only() -> None:
    changed = [
        "tests/capabilities.toml#precision_land",
        "tests/capabilities.toml#arm_takeoff",
    ]
    assert flight_relevant(changed, "08_precision_land.py", "precision_land") == [
        "tests/capabilities.toml#precision_land"
    ]


def test_changed_registry_claims_names_only_modified_entries() -> None:
    old = """
[capabilities.a]
description = "old"
[capabilities.b]
description = "same"
"""
    new = """
[capabilities.a]
description = "new"
[capabilities.b]
description = "same"
"""
    assert changed_registry_claims(old, new) == ["a"]


def test_dirty_flight_paths_filters_porcelain() -> None:
    porcelain = " M src/core/x.py\n?? docs/notes.md\n M tests/scenarios/01_arm_takeoff.py\n"
    assert dirty_flight_paths(porcelain, "01_arm_takeoff.py") == [
        "src/core/x.py",
        "tests/scenarios/01_arm_takeoff.py",
    ]


def test_dirty_flight_paths_checks_both_sides_of_rename() -> None:
    porcelain = "R  src/core/x.py -> docs/x.py\n"
    assert dirty_flight_paths(porcelain, "01_arm_takeoff.py") == ["src/core/x.py"]


def test_dirty_flight_paths_filters_registry_to_own_claim() -> None:
    porcelain = " M tests/capabilities.toml\n"
    assert dirty_flight_paths(
        porcelain,
        "01_arm_takeoff.py",
        "arm_takeoff",
        ["hover_hold", "arm_takeoff"],
    ) == ["tests/capabilities.toml#arm_takeoff"]


def test_record_rejects_registry_renamed_out_of_place(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry = {
        "capabilities": {
            "arm_takeoff": {
                "description": "d",
                "requires": [],
                "platforms": ["sim"],
                "scenario_file": "01_arm_takeoff.py",
            }
        }
    }
    monkeypatch.setattr(capabilities, "_load", lambda: registry)
    monkeypatch.chdir(tmp_path)
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "scenario_01_arm_takeoff.json").write_text(json.dumps(_ARM_REPORT))

    def fake_run(args: list[str], **kwargs: object) -> SimpleNamespace:
        if args == ["git", "status", "--porcelain"]:
            return SimpleNamespace(
                returncode=0,
                stdout=("R  tests/capabilities.toml -> docs/capabilities.toml\n"),
            )
        if args == ["git", "show", "HEAD:tests/capabilities.toml"]:
            return SimpleNamespace(returncode=1, stdout="")
        raise AssertionError(args)

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = CliRunner().invoke(capabilities.app, ["record", "arm_takeoff"])

    assert result.exit_code == 3
    assert "DIRTY TREE" in result.output


def test_record_unknown_claim_is_usage_error() -> None:
    result = CliRunner().invoke(capabilities.app, ["record", "ghost_claim"])
    assert result.exit_code == 2
    assert "NO SUCH LEAF CLAIM" in result.output


def test_record_rejects_mismatched_report_scenario(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry = {
        "capabilities": {
            "arm_takeoff": {
                "description": "d",
                "requires": [],
                "platforms": ["sim"],
                "scenario_file": "01_arm_takeoff.py",
            }
        }
    }
    monkeypatch.setattr(capabilities, "_load", lambda: registry)
    monkeypatch.chdir(tmp_path)
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "scenario_01_arm_takeoff.json").write_text(json.dumps(_REPORT))

    result = CliRunner().invoke(capabilities.app, ["record", "arm_takeoff"])

    assert result.exit_code == 3
    assert "REPORT SCENARIO MISMATCH" in result.output


def test_record_rejects_leaf_without_sim_platform(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = {
        "capabilities": {
            "hardware_only": {
                "description": "d",
                "requires": [],
                "platforms": ["hw"],
                "scenario_file": "10_hardware_only.py",
            }
        }
    }
    monkeypatch.setattr(capabilities, "_load", lambda: registry)

    result = CliRunner().invoke(capabilities.app, ["record", "hardware_only"])

    assert result.exit_code == 3
    assert "SIM NOT DECLARED" in result.output


def test_report_fresh_requires_every_revision_boundary() -> None:
    assert report_is_fresh(101.0, 100.0)
    assert report_is_fresh(100.0, 100.0)
    assert not report_is_fresh(99.0, 100.0)
    assert not report_is_fresh(101.0, 100.0, 102.0)


def test_git_state_mtimes_include_checkout_and_branch_ref(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    git_dir = tmp_path / "worktree-git"
    common_dir = tmp_path / "common-git"
    head = git_dir / "HEAD"
    branch = common_dir / "refs" / "heads" / "feature"
    git_dir.mkdir()
    branch.parent.mkdir(parents=True)
    head.write_text("ref: refs/heads/feature\n")
    branch.write_text("abc123\n")
    head.touch()
    branch.touch()
    head_mtime = head.stat().st_mtime
    branch_mtime = branch.stat().st_mtime

    def fake_run(args: list[str], **kwargs: object) -> SimpleNamespace:
        if args == ["git", "rev-parse", "--absolute-git-dir"]:
            return SimpleNamespace(returncode=0, stdout=f"{git_dir}\n")
        if args == ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"]:
            return SimpleNamespace(returncode=0, stdout=f"{common_dir}\n")
        raise AssertionError(args)

    monkeypatch.setattr(cap_evidence.subprocess, "run", fake_run)

    assert git_state_mtimes() == [head_mtime, branch_mtime]


def test_record_writes_pass_evidence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    registry = {
        "capabilities": {
            "arm_takeoff": {
                "description": "d",
                "requires": [],
                "platforms": ["sim"],
                "scenario_file": "01_arm_takeoff.py",
            }
        }
    }
    monkeypatch.setattr(capabilities, "_load", lambda: registry)
    monkeypatch.setattr(cap_evidence, "EVIDENCE_ROOT", tmp_path / "evidence")
    monkeypatch.setattr(cap_evidence, "git_state_mtimes", lambda: [0.0])
    monkeypatch.chdir(tmp_path)
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "scenario_01_arm_takeoff.json").write_text(json.dumps(_ARM_REPORT))

    def fake_run(args: list[str], **kwargs: object) -> SimpleNamespace:
        if args[:3] == ["git", "status", "--porcelain"]:
            return SimpleNamespace(returncode=0, stdout="")
        if args[:3] == ["git", "rev-parse", "--short"]:
            return SimpleNamespace(returncode=0, stdout="abc1234\n")
        if args == ["git", "show", "-s", "--format=%ct", "HEAD"]:
            return SimpleNamespace(returncode=0, stdout="0\n")
        raise AssertionError(args)

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = CliRunner().invoke(capabilities.app, ["record", "arm_takeoff"])

    assert result.exit_code == 0
    assert "RECORDED arm_takeoff sim PASS @ abc1234" in result.output
    records = load_records(tmp_path / "evidence", "arm_takeoff")
    assert records[0]["commit"] == "abc1234"
