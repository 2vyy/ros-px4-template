"""Unit tests for StructuredLogger logfmt-on-stdout (no rclpy, no files)."""

from __future__ import annotations

from unittest.mock import MagicMock

from ros_px4_template_core.lib.structured_logger import StructuredLogger, render_logfmt


def _mock_node(sim_ns: int = 1_000_000_000) -> MagicMock:
    node = MagicMock()
    clock = MagicMock()
    clock.now.return_value.nanoseconds = sim_ns
    node.get_clock.return_value = clock
    return node


def test_event_renders_logfmt_to_stdout(capsys) -> None:
    slog = StructuredLogger(_mock_node())
    slog.event("PHASE_CHANGE", phase="hover", alt_m=3.0)
    out = capsys.readouterr().out.strip()
    assert out.startswith("t=")
    assert "level=info" in out
    assert "event=PHASE_CHANGE" in out
    assert "phase=hover" in out
    assert "alt_m=3.0" in out
    # event lines carry no ROS-logger mirror call
    # (node is a MagicMock; nothing should call get_logger)


def test_info_warn_error_levels(capsys) -> None:
    slog = StructuredLogger(_mock_node())
    slog.info("hello")
    slog.warn("careful")
    slog.error("boom", code=7)
    lines = capsys.readouterr().out.strip().splitlines()
    assert "level=info" in lines[0]
    assert "msg=hello" in lines[0]
    assert "level=warn" in lines[1]
    assert "msg=careful" in lines[1]
    assert "level=error" in lines[2]
    assert "msg=boom" in lines[2]
    assert "code=7" in lines[2]


def test_sim_t_present_when_clock_valid(capsys) -> None:
    StructuredLogger(_mock_node(sim_ns=2_500_000_000)).info("x")
    assert "sim_t=2.500" in capsys.readouterr().out


def test_sim_t_omitted_when_clock_zero(capsys) -> None:
    StructuredLogger(_mock_node(sim_ns=0)).info("x")
    assert "sim_t=" not in capsys.readouterr().out


def test_value_quoting() -> None:
    assert render_logfmt("info", "msg", "two words", None, {}).count('msg="two words"') == 1
    assert 'k="a=b"' in render_logfmt("info", "msg", "m", None, {"k": "a=b"})
    assert "n=3" in render_logfmt("info", "msg", "m", None, {"n": 3})


def test_close_is_noop(capsys) -> None:
    slog = StructuredLogger(_mock_node())
    slog.close()  # nodes call this in destroy_node; must not raise or print
    assert capsys.readouterr().out == ""
