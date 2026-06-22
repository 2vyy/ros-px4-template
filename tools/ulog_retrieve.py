#!/usr/bin/env python3
"""Copy the current run's PX4 SITL ULog into its logs/runs/<id>/ directory.

SITL-only and best-effort: PX4 SITL writes ULogs under
$PX4_DIR/build/px4_sitl_default/rootfs/log/<date>/<time>.ulg. At teardown of a
recorded `just sim` run we copy the newest ULog that was written during this run
to logs/runs/<id>/session.ulg, so a run pairs its bag with its ULog for skein.

A freshness guard (mtime >= the run dir's start time) prevents a stale ULog from
a previous boot from being mistaken for this run's. Never raises — a miss leaves
the run without a ULog and warns, rather than failing teardown.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

_SITL_LOG_SUBPATH = "build/px4_sitl_default/rootfs/log"


def _px4_log_root(px4_dir: str | None) -> Path | None:
    px4_dir = px4_dir if px4_dir is not None else os.environ.get("PX4_DIR", "").strip()
    if not px4_dir:
        return None
    root = Path(px4_dir) / _SITL_LOG_SUBPATH
    return root if root.is_dir() else None


def find_latest_ulog(log_root: Path, *, since_mtime: float) -> Path | None:
    """Return the newest *.ulg under log_root whose mtime is >= since_mtime, or
    None if there is no such (fresh) ULog. Pure over the filesystem under log_root."""
    candidates: list[tuple[float, Path]] = []
    for ulg in log_root.rglob("*.ulg"):
        try:
            mtime = ulg.stat().st_mtime
        except OSError:
            continue
        if mtime >= since_mtime:
            candidates.append((mtime, ulg))
    if not candidates:
        return None
    return max(candidates, key=lambda t: t[0])[1]


def retrieve(
    run_dir: Path,
    *,
    px4_dir: str | None = None,
    copy=shutil.copy2,
) -> Path | None:
    """Copy the run's PX4 SITL ULog into run_dir/session.ulg. Returns the
    destination path on success, else None. Best-effort: never raises."""
    try:
        resolved = run_dir.resolve()  # run_dir may be the logs/runs/latest symlink
        if not resolved.is_dir():
            print(f"Warning: ULog retrieval skipped — no run dir at {run_dir}", file=sys.stderr)
            return None
        log_root = _px4_log_root(px4_dir)
        if log_root is None:
            print(
                "Warning: ULog retrieval skipped — PX4_DIR unset or "
                f"{_SITL_LOG_SUBPATH} missing (SITL-only).",
                file=sys.stderr,
            )
            return None
        since = resolved.stat().st_mtime
        src = find_latest_ulog(log_root, since_mtime=since)
        if src is None:
            print(
                "Warning: no fresh PX4 ULog found for this run under "
                f"{log_root} (SITL may not have logged this run).",
                file=sys.stderr,
            )
            return None
        dest = resolved / "session.ulg"
        copy(str(src), str(dest))
        print(f"Copied PX4 ULog {src.name} -> {dest}")
        return dest
    except Exception as e:  # retrieval is best-effort, never fatal
        print(f"Warning: ULog retrieval failed: {e}", file=sys.stderr)
        return None
