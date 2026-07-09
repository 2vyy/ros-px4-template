from __future__ import annotations

import socket
import sys

import pytest

import preflight


def test_port_free_on_unused_port() -> None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()

    assert preflight._port_free(port) is True


def test_port_busy_detected() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        port = sock.getsockname()[1]

        assert preflight._port_free(port) is False


def test_check_prints_fail_with_detail(capsys: pytest.CaptureFixture[str]) -> None:
    assert preflight._check("x", False, "why") is False

    out = capsys.readouterr().out
    assert "[FAIL]" in out
    assert "why" in out


def test_check_hides_detail_on_ok(capsys: pytest.CaptureFixture[str]) -> None:
    assert preflight._check("x", True, "why") is True

    out = capsys.readouterr().out
    assert "[OK]" in out
    assert "why" not in out


def test_git_branch_unknown_outside_repo(tmp_path) -> None:
    assert preflight._git_branch(tmp_path) == "<unknown>"


def test_main_fails_with_empty_env(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    monkeypatch.delenv("ROS_SETUP", raising=False)
    monkeypatch.delenv("PX4_DIR", raising=False)
    monkeypatch.setattr(sys, "argv", ["preflight", "--mode", "px4"])
    monkeypatch.setattr(preflight.shutil, "which", lambda _name: None)

    with pytest.raises(SystemExit) as exc:
        preflight.main()

    assert exc.value.code == 1
    assert "Preflight FAILED" in capsys.readouterr().out
