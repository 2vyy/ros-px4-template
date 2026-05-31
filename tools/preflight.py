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
import shlex
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


def _port_pid(port: int, proto: str = "tcp") -> str:
    """Return 'pid NNNN (name)' for the process holding *port*, or ''."""
    try:
        r = subprocess.run(
            ["ss", "-lnp", f"sport = :{port}"],
            capture_output=True,
            text=True,
            timeout=3,
        )
        for line in r.stdout.splitlines():
            if f":{port}" in line and "users:" in line:
                import re

                m = re.search(r'users:\(\("([^"]+)",pid=(\d+)', line)
                if m:
                    return f"pid {m.group(2)} ({m.group(1)})"
    except Exception:
        pass
    return ""


def _git_branch(path: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(path), "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else "<unknown>"


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", default="gui")
    args = parser.parse_args()

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

    if args.mode not in ("px4", "edit"):
        port_8888_free = _port_free(8888)
        pid_8888 = "" if port_8888_free else _port_pid(8888, "tcp")
        results.append(
            _check(
                "Port 8888 (MicroXRCEAgent) free",
                port_8888_free,
                f"already in use {pid_8888} — run: just sim-stop".strip(),
            )
        )
        port_9090_free = _port_free(9090)
        pid_9090 = "" if port_9090_free else _port_pid(9090, "tcp")
        results.append(
            _check(
                "Port 9090 (rosbridge) free",
                port_9090_free,
                f"already in use {pid_9090} — run: just sim-stop".strip(),
            )
        )

    uv_ok = shutil.which("uv") is not None
    results.append(_check("uv on PATH", uv_ok))

    if args.mode == "hw":
        import shutil as _shutil

        microxrce_ok = _shutil.which("MicroXRCEAgent") is not None
        results.append(
            _check(
                "MicroXRCEAgent binary on PATH",
                microxrce_ok,
                "install: pip install micro-xrce-dds-agent or build from source"
                if not microxrce_ok
                else "",
            )
        )

        serial_dev = os.environ.get("HARDWARE_SERIAL_PORT", "/dev/ttyUSB0")
        serial_ok = Path(serial_dev).exists()
        results.append(
            _check(
                f"Serial device exists ({serial_dev})",
                serial_ok,
                "device not found — check USB cable and set HARDWARE_SERIAL_PORT in .env"
                if not serial_ok
                else "",
            )
        )

    pymavlink_ok = False
    if uv_ok:
        r = subprocess.run(
            ["uv", "run", "python", "-c", "import pymavlink"],
            cwd=ROOT,
            capture_output=True,
            timeout=30,
        )
        pymavlink_ok = r.returncode == 0
    results.append(
        _check(
            "pymavlink importable (uv venv)",
            pymavlink_ok,
            "run: uv sync" if not pymavlink_ok else "",
        )
    )

    rosbridge_py_ok = False
    if ros_setup and Path(ros_setup).exists() and args.mode not in ("px4", "edit"):
        r = subprocess.run(
            [
                "bash",
                "-lc",
                f"source {shlex.quote(ros_setup)} && "
                "env -u PYTHONPATH -u VIRTUAL_ENV /usr/bin/python3 -c 'import tornado, numpy'",
            ],
            capture_output=True,
            timeout=30,
        )
        rosbridge_py_ok = r.returncode == 0
        results.append(
            _check(
                "rosbridge Python deps (tornado, numpy via apt)",
                rosbridge_py_ok,
                "run: sudo apt install ros-jazzy-rosbridge-suite",
            )
        )

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
