"""Committed claims evidence ledger tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cap_evidence import (
    build_record,
    changed_registry_claims,
    flight_relevant,
    load_records,
    write_record,
)

_REPORT = {
    "scenario": "08_precision_land",
    "passed": True,
    "elapsed_s": 141.2,
    "detail": {"xy_err": 0.06},
}


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
