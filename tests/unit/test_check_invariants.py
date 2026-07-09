"""Unit tests for repository invariant checks."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

import check_invariants


def _make_px4_msgs_checkout(tmp_path: Path, branch: str) -> Path:
    px4_msgs = tmp_path / "src" / "px4_msgs"
    git_dir = px4_msgs / ".git"
    git_dir.mkdir(parents=True)
    (git_dir / "HEAD").write_text(f"ref: refs/heads/{branch}\n", encoding="utf-8")
    return px4_msgs


def test_px4_msgs_branch_falls_back_to_git_metadata_when_git_missing(
    tmp_path: Path, monkeypatch
) -> None:
    px4_msgs = _make_px4_msgs_checkout(tmp_path, check_invariants.EXPECTED_BRANCH)

    def missing_git(*args, **kwargs):
        raise FileNotFoundError("git")

    monkeypatch.setattr(subprocess, "run", missing_git)

    assert check_invariants.check_px4_msgs_branch(px4_msgs)


def test_px4_msgs_branch_fallback_rejects_wrong_branch(tmp_path: Path, monkeypatch) -> None:
    px4_msgs = _make_px4_msgs_checkout(tmp_path, "main")

    def missing_git(*args, **kwargs):
        raise FileNotFoundError("git")

    monkeypatch.setattr(subprocess, "run", missing_git)

    assert not check_invariants.check_px4_msgs_branch(px4_msgs)
