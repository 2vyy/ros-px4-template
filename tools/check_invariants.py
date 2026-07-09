#!/usr/bin/env python3
"""Repo invariant checks not expressible in Ruff. Run via `just check-invariants`."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PX4_MSGS = ROOT / "src" / "px4_msgs"
EXPECTED_BRANCH = "release/1.17"


def _fail(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)


def _warn(msg: str) -> None:
    print(f"WARNING: {msg}", file=sys.stderr)


def _branch_from_git_metadata(git_path: Path) -> str | None:
    """Read the current branch from .git/HEAD when the git executable is unavailable."""
    if git_path.is_file():
        raw = git_path.read_text(encoding="utf-8").strip()
        if not raw.startswith("gitdir:"):
            return None
        git_path = (git_path.parent / raw.removeprefix("gitdir:").strip()).resolve()

    head = git_path / "HEAD"
    if not head.is_file():
        return None
    raw_head = head.read_text(encoding="utf-8").strip()
    prefix = "ref: refs/heads/"
    if raw_head.startswith(prefix):
        return raw_head.removeprefix(prefix)
    return "HEAD"


def check_px4_msgs_branch(px4_msgs: Path = PX4_MSGS) -> bool:
    if not px4_msgs.is_dir():
        _fail(f"Missing {px4_msgs} — run: just clone-px4-msgs")
        return False
    try:
        result = subprocess.run(
            ["git", "-C", str(px4_msgs), "rev-parse", "--abbrev-ref", "HEAD"],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            _fail(f"px4_msgs is not a git checkout ({px4_msgs})")
            return False
        branch = result.stdout.strip()
    except FileNotFoundError:
        branch = _branch_from_git_metadata(px4_msgs / ".git")
        if branch is None:
            _fail(f"px4_msgs is not a git checkout ({px4_msgs})")
            return False
    if branch != EXPECTED_BRANCH:
        _fail(
            f"px4_msgs on branch {branch!r}, expected {EXPECTED_BRANCH!r} "
            f"(AGENTS.md invariant — matches PX4 v1.17)"
        )
        return False
    print(f"OK px4_msgs branch {branch}")
    return True


def main() -> None:
    ok = check_px4_msgs_branch()
    if not ok:
        sys.exit(1)
    print("All invariant checks passed.")


if __name__ == "__main__":
    main()
