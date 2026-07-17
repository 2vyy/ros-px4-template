"""Derived claims rung tests."""

from __future__ import annotations

from datetime import UTC, datetime

from cap_status import RUNG_ORDER, RungInfo, derive_all, display, evidence_age

_OK = lambda *_: (True, "")  # noqa: E731
_NO = lambda *_: (False, "missing")  # noqa: E731


def _reg(**caps: dict) -> dict:
    return {"capabilities": caps}


def _leaf(**kw: object) -> dict:
    entry: dict = {
        "description": "d",
        "platforms": ["sim"],
        "scenario_file": "01_arm_takeoff.py",
        "requires": [],
    }
    entry.update(kw)
    return entry


def _ev(commit: str = "aaa") -> dict:
    return {
        "claim": "a",
        "platform": "sim",
        "commit": commit,
        "verdict": "PASS",
        "run_id": "20260717_000000",
        "elapsed_s": 1.0,
        "detail": {},
        "conditions": {},
        "grade": None,
    }


def test_declared_when_artifacts_missing() -> None:
    out = derive_all(_reg(a=_leaf()), {}, lambda commit: [], _NO, _OK)
    assert out["a"].rung == "declared"
    assert "missing" in out["a"].reason


def test_simulated_when_artifacts_ok_no_evidence() -> None:
    out = derive_all(_reg(a=_leaf()), {}, lambda commit: [], _OK, _OK)
    assert out["a"].rung == "simulated"


def test_sim_flown_with_fresh_evidence() -> None:
    out = derive_all(_reg(a=_leaf()), {"a": [_ev()]}, lambda commit: [], _OK, _OK)
    assert out["a"].rung == "sim-flown"


def test_stale_when_flight_paths_changed() -> None:
    out = derive_all(
        _reg(a=_leaf()),
        {"a": [_ev("aaa")]},
        lambda commit: ["src/core/x.py"],
        _OK,
        _OK,
    )
    assert out["a"].rung == "sim-flown-stale"
    assert "aaa" in display(out["a"])


def test_stale_when_own_registry_entry_changed() -> None:
    out = derive_all(
        _reg(a=_leaf()),
        {"a": [_ev("aaa")]},
        lambda commit: ["tests/capabilities.toml#a"],
        _OK,
        _OK,
    )
    assert out["a"].rung == "sim-flown-stale"


def test_other_registry_entry_change_stays_fresh() -> None:
    out = derive_all(
        _reg(a=_leaf()),
        {"a": [_ev("aaa")]},
        lambda commit: ["tests/capabilities.toml#b"],
        _OK,
        _OK,
    )
    assert out["a"].rung == "sim-flown"


def test_stale_when_commit_unknown() -> None:
    out = derive_all(_reg(a=_leaf()), {"a": [_ev()]}, lambda commit: None, _OK, _OK)
    assert out["a"].rung == "sim-flown-stale"
    assert "commit_unknown" in out["a"].reason


def test_doc_only_change_stays_fresh() -> None:
    out = derive_all(
        _reg(a=_leaf()),
        {"a": [_ev()]},
        lambda commit: ["docs/README.md"],
        _OK,
        _OK,
    )
    assert out["a"].rung == "sim-flown"


def test_mission_failing_holds_at_declared() -> None:
    out = derive_all(_reg(a=_leaf(mission="hover")), {}, lambda commit: [], _OK, _NO)
    assert out["a"].rung == "declared"
    assert "missing" in out["a"].reason


def test_composite_is_min_of_requires() -> None:
    registry = _reg(
        a=_leaf(),
        b=_leaf(scenario_file="02_hover_hold.py", requires=["a"]),
        top={"description": "d", "requires": ["a", "b"]},
    )
    records = {"a": [_ev()], "b": []}
    out = derive_all(registry, records, lambda commit: [], _OK, _OK)
    assert out["a"].rung == "sim-flown"
    assert out["b"].rung == "simulated"
    assert out["top"].rung == "simulated"


def test_stale_composite_preserves_child_evidence() -> None:
    registry = _reg(
        a=_leaf(),
        top={"description": "d", "requires": ["a"]},
    )
    out = derive_all(
        registry,
        {"a": [_ev("aaa")]},
        lambda commit: ["src/core/x.py"],
        _OK,
        _OK,
    )
    assert out["top"].rung == "sim-flown-stale"
    assert "aaa" in display(out["top"])


def test_rung_order_is_total() -> None:
    assert RUNG_ORDER == ("declared", "simulated", "sim-flown-stale", "sim-flown")


def test_evidence_age_uses_utc_run_id() -> None:
    now = datetime(2026, 7, 19, 3, 0, tzinfo=UTC)
    assert evidence_age(_ev(), now=now) == "2d"


def test_evidence_age_handles_invalid_run_id() -> None:
    assert evidence_age({"run_id": "invalid"}) == "?"


def test_display_uses_exact_stale_form() -> None:
    assert display(RungInfo("sim-flown-stale", evidence=_ev("9d12d49"))) == (
        "sim-flown (stale, since 9d12d49)"
    )
