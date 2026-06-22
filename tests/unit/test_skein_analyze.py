"""Unit tests for skein analyze helpers (no skein/ROS required)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

import pytest

import skein_analyze


# --- overlay_argv -----------------------------------------------------------


def test_overlay_argv_both_bag_and_ulog() -> None:
    skein_dir = Path("/skein")
    bag = Path("/run/bag/bag_0.mcap")
    ulog = Path("/run/session.ulg")
    out = Path("/run/aligned.mcap")

    argv = skein_analyze.overlay_argv(skein_dir, bag=bag, ulog=ulog, out=out)

    assert argv[:7] == ["uv", "run", "--project", str(skein_dir), "skein", "overlay", "--out"]
    assert argv[7] == str(out)
    assert "--bag" in argv and str(bag) in argv
    assert "--ulog" in argv and str(ulog) in argv


def test_overlay_argv_bag_only() -> None:
    skein_dir = Path("/skein")
    bag = Path("/run/bag/bag_0.mcap")
    out = Path("/run/aligned.mcap")

    argv = skein_analyze.overlay_argv(skein_dir, bag=bag, ulog=None, out=out)

    assert "--bag" in argv and str(bag) in argv
    assert "--ulog" not in argv


def test_overlay_argv_ulog_only() -> None:
    skein_dir = Path("/skein")
    ulog = Path("/run/session.ulg")
    out = Path("/run/aligned.mcap")

    argv = skein_analyze.overlay_argv(skein_dir, bag=None, ulog=ulog, out=out)

    assert "--ulog" in argv and str(ulog) in argv
    assert "--bag" not in argv


# --- query_argv --------------------------------------------------------------


def test_query_argv_minimal() -> None:
    skein_dir = Path("/skein")
    artifact = Path("/run/aligned.mcap")

    argv = skein_analyze.query_argv(skein_dir, artifact)

    assert argv == ["uv", "run", "--project", str(skein_dir), "skein", "query", str(artifact)]


def test_query_argv_with_all_options() -> None:
    skein_dir = Path("/skein")
    artifact = Path("/run/aligned.mcap")

    argv = skein_analyze.query_argv(
        skein_dir, artifact, channel="vehicle_local_position", where="z < -2", stats=True
    )

    assert "-c" in argv and "vehicle_local_position" in argv
    assert "--where" in argv and "z < -2" in argv
    assert "--stats" in argv


def test_query_argv_omits_unset_options() -> None:
    skein_dir = Path("/skein")
    artifact = Path("/run/aligned.mcap")

    argv = skein_analyze.query_argv(skein_dir, artifact, channel=None, where=None, stats=False)

    assert "-c" not in argv
    assert "--where" not in argv
    assert "--stats" not in argv


# --- resolve_skein_dir --------------------------------------------------------


def test_resolve_skein_dir_returns_path_when_pyproject_exists(tmp_path) -> None:
    fake_skein = tmp_path / "skein"
    fake_skein.mkdir()
    (fake_skein / "pyproject.toml").write_text("[project]\nname = 'skein'\n")

    result = skein_analyze.resolve_skein_dir(str(fake_skein))

    assert result == fake_skein


def test_resolve_skein_dir_raises_when_missing(tmp_path) -> None:
    missing = tmp_path / "nope"

    with pytest.raises(skein_analyze.AnalyzeError):
        skein_analyze.resolve_skein_dir(str(missing))


# --- resolve_run_dir ----------------------------------------------------------


def test_resolve_run_dir_returns_dir_for_existing_run(tmp_path) -> None:
    runs_dir = tmp_path / "runs"
    run_dir = runs_dir / "20260622_120000"
    run_dir.mkdir(parents=True)

    result = skein_analyze.resolve_run_dir("20260622_120000", runs_dir=runs_dir)

    assert result == run_dir


def test_resolve_run_dir_raises_for_missing_run(tmp_path) -> None:
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()

    with pytest.raises(skein_analyze.AnalyzeError):
        skein_analyze.resolve_run_dir("nope", runs_dir=runs_dir)


# --- find_bag_mcap -------------------------------------------------------------


def test_find_bag_mcap_returns_mcap_inside_bag_dir(tmp_path) -> None:
    run_dir = tmp_path / "run"
    bag_dir = run_dir / "bag"
    bag_dir.mkdir(parents=True)
    mcap = bag_dir / "bag_0.mcap"
    mcap.write_bytes(b"mcap-bytes")

    result = skein_analyze.find_bag_mcap(run_dir)

    assert result == mcap


def test_find_bag_mcap_returns_none_when_bag_dir_missing(tmp_path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    result = skein_analyze.find_bag_mcap(run_dir)

    assert result is None


def test_find_bag_mcap_returns_none_when_no_mcap_present(tmp_path) -> None:
    run_dir = tmp_path / "run"
    bag_dir = run_dir / "bag"
    bag_dir.mkdir(parents=True)
    (bag_dir / "metadata.yaml").write_text("rosbag2_bagfile_information: {}\n")

    result = skein_analyze.find_bag_mcap(run_dir)

    assert result is None
