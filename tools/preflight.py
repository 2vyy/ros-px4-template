#!/usr/bin/env python3
"""Pre-flight checks before launching the sim stack.

Checks:
  - ROS_SETUP file exists (from .env)
  - PX4_DIR and its px4 binary exist
  - src/px4_msgs is on branch release/1.17
  - Ports 8888 (MicroXRCEAgent) and 9090 (rosbridge) are free
  - uv is available on PATH

Exit 0 if all pass, 1 on any failure.
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _check(label: str, ok: bool, detail: str = "", always_show_detail: bool = False) -> bool:
    status = "[OK]  " if ok else "[FAIL]"
    show = detail and (not ok or always_show_detail)
    suffix = f"  {detail}" if show else ""
    print(f"  {status} {label}{suffix}")
    return ok


def _port_free(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            return False  # something is listening
    except OSError:
        return True


def _git_branch(path: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(path), "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else "<unknown>"


def main() -> None:
    ros_setup = os.environ.get("ROS_SETUP", "")
    px4_dir = os.environ.get("PX4_DIR", "")
    px4_msgs = ROOT / "src" / "px4_msgs"

    results = []

    results.append(
        _check(
            "ROS_SETUP file exists",
            bool(ros_setup) and Path(ros_setup).exists(),
            ros_setup or "(ROS_SETUP not set)",
            always_show_detail=True,
        )
    )

    px4_bin = Path(px4_dir) / "build" / "px4_sitl_default" / "bin" / "px4" if px4_dir else None
    results.append(
        _check(
            "PX4_DIR set and px4 binary exists",
            bool(px4_bin and px4_bin.exists()),
            str(px4_bin) if px4_bin else "(PX4_DIR not set)",
            always_show_detail=True,
        )
    )

    branch = _git_branch(px4_msgs) if px4_msgs.is_dir() else "<missing>"
    results.append(
        _check(
            "src/px4_msgs on release/1.17",
            branch == "release/1.17",
            f"branch={branch}",
            always_show_detail=True,
        )
    )

    results.append(
        _check(
            "Port 8888 (MicroXRCEAgent) free",
            _port_free(8888),
            "already in use — run: just sim-stop",
        )
    )
    results.append(
        _check(
            "Port 9090 (rosbridge) free", _port_free(9090), "already in use — run: just sim-stop"
        )
    )

    results.append(_check("uv on PATH", shutil.which("uv") is not None))

    ws_install = ROOT / "install" / "setup.bash"
    results.append(
        _check(
            "Workspace built (install/setup.bash exists)", ws_install.exists(), "run: just build"
        )
    )

    all_ok = all(results)
    print()
    print("Preflight OK." if all_ok else "Preflight FAILED — fix issues above before launching.")
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
