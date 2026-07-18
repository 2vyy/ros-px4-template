"""Claims registry form validation tests."""

from __future__ import annotations

from pathlib import Path

import pytest

import check_capabilities
from check_capabilities import validate_registry


def _entry(**kw: object) -> dict:
    base: dict = {"description": "d", "platforms": ["sim"]}
    base.update(kw)
    return base


def test_valid_registry_returns_no_errors() -> None:
    data = {
        "capabilities": {
            "arm_takeoff": _entry(scenario_file="01_arm_takeoff.py", requires=[]),
            "challenge": {"description": "d", "requires": ["arm_takeoff"]},
        }
    }
    assert validate_registry(data) == []


def test_unknown_requires_id_is_named() -> None:
    data = {"capabilities": {"a": _entry(scenario_file="s.py", requires=["ghost"])}}
    errs = validate_registry(data)
    assert len(errs) == 1
    assert "a" in errs[0]
    assert "ghost" in errs[0]


def test_cycle_is_rejected() -> None:
    data = {
        "capabilities": {
            "a": _entry(scenario_file="a.py", requires=["b"]),
            "b": _entry(scenario_file="b.py", requires=["a"]),
        }
    }
    errors = validate_registry(data)
    assert any(error.startswith("a:") and "cycle" in error for error in errors)


def test_composite_with_empty_requires_is_rejected() -> None:
    data = {"capabilities": {"c": {"description": "d", "requires": []}}}
    assert any("composite" in e for e in validate_registry(data))


def test_leaf_without_platforms_is_rejected() -> None:
    data = {"capabilities": {"a": {"description": "d", "scenario_file": "a.py"}}}
    assert any("platforms" in e for e in validate_registry(data))


def test_unknown_platform_value_is_rejected() -> None:
    data = {"capabilities": {"a": _entry(scenario_file="a.py", platforms=["moon"])}}
    assert any("moon" in e for e in validate_registry(data))


def test_unknown_composite_platform_value_is_rejected() -> None:
    data = {
        "capabilities": {
            "leaf": _entry(scenario_file="a.py", requires=[]),
            "challenge": {
                "description": "d",
                "requires": ["leaf"],
                "platforms": ["moon"],
            },
        }
    }
    errors = validate_registry(data)
    assert any("challenge" in error and "moon" in error for error in errors)


def test_composite_platforms_must_be_a_list() -> None:
    data = {
        "capabilities": {
            "leaf": _entry(scenario_file="a.py", requires=[]),
            "challenge": {
                "description": "d",
                "requires": ["leaf"],
                "platforms": "sim",
            },
        }
    }
    errors = validate_registry(data)
    assert any(
        "challenge" in error and "platforms" in error and "list" in error for error in errors
    )


def test_wrong_field_types_are_rejected() -> None:
    data = {"capabilities": {"a": _entry(scenario_file="a.py", requires="arm")}}
    assert any("requires" in e and "list" in e for e in validate_registry(data))


def test_numeric_requires_returns_error_without_crashing() -> None:
    data = {"capabilities": {"a": _entry(scenario_file="a.py", requires=7)}}
    errors = validate_registry(data)
    assert any("a" in error and "requires" in error and "list" in error for error in errors)


def test_legacy_status_field_is_rejected() -> None:
    data = {"capabilities": {"a": _entry(scenario_file="a.py", status="verified")}}
    assert any("status" in e and "derived" in e for e in validate_registry(data))


def test_capabilities_must_be_a_table() -> None:
    assert any(
        "capabilities" in e and "table" in e for e in validate_registry({"capabilities": []})
    )


def test_claim_entry_must_be_a_table() -> None:
    data = {"capabilities": {"a": "not a table"}}
    assert any("a" in e and "table" in e for e in validate_registry(data))


def test_main_prints_clean_verdict(tmp_path: Path, monkeypatch, capsys) -> None:
    registry = tmp_path / "capabilities.toml"
    registry.write_text(
        '[capabilities.a]\ndescription = "d"\nscenario_file = "a.py"\n'
        'platforms = ["sim"]\nrequires = []\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(check_capabilities, "REGISTRY", registry)

    check_capabilities.main()

    assert capsys.readouterr().out.strip() == "REGISTRY OK: 1 claims, DAG valid"


@pytest.mark.parametrize(
    ("content", "detail"),
    [
        ("capabilities = 7\n", "capabilities"),
        ("[capabilities.a\n", "invalid TOML"),
    ],
)
def test_main_prints_invalid_verdict_without_traceback(
    tmp_path: Path, monkeypatch, capsys, content: str, detail: str
) -> None:
    registry = tmp_path / "capabilities.toml"
    registry.write_text(content, encoding="utf-8")
    monkeypatch.setattr(check_capabilities, "REGISTRY", registry)

    with pytest.raises(SystemExit) as exc:
        check_capabilities.main()

    assert exc.value.code == 1
    stderr = capsys.readouterr().err
    assert detail in stderr
    assert "REGISTRY INVALID" in stderr
