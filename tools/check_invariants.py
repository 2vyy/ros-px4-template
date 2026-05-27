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


def check_px4_msgs_branch() -> bool:
    if not PX4_MSGS.is_dir():
        _fail(f"Missing {PX4_MSGS} — run: just clone-px4-msgs")
        return False
    result = subprocess.run(
        ["git", "-C", str(PX4_MSGS), "rev-parse", "--abbrev-ref", "HEAD"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        _fail(f"px4_msgs is not a git checkout ({PX4_MSGS})")
        return False
    branch = result.stdout.strip()
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
