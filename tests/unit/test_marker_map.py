"""Unit tests for the pure marker-map parser (no ROS graph)."""

from __future__ import annotations

from ros_px4_template_core.lib.marker_map import parse_marker_map


def test_wellformed_two_markers() -> None:
    doc = {"markers": {0: {"x": 1.0, "y": 2.0, "z": 3.0}, 5: {"x": -1.0, "y": 0.0, "z": 4.5}}}
    m, warnings = parse_marker_map(doc)
    assert m == {0: (1.0, 2.0, 3.0), 5: (-1.0, 0.0, 4.5)}
    assert warnings == []


def test_integer_string_keys_coerce() -> None:
    doc = {"markers": {"0": {"x": 0.0, "y": 0.0, "z": 0.0}, "1": {"x": 1.0, "y": 1.0, "z": 1.0}}}
    m, warnings = parse_marker_map(doc)
    assert set(m) == {0, 1}
    assert all(isinstance(k, int) for k in m)
    assert warnings == []


def test_entry_missing_z_is_skipped() -> None:
    doc = {"markers": {0: {"x": 1.0, "y": 2.0}, 1: {"x": 0.0, "y": 0.0, "z": 0.0}}}
    m, warnings = parse_marker_map(doc)
    assert set(m) == {1}
    assert len(warnings) == 1
    assert "marker 0" in warnings[0]


def test_non_numeric_value_is_skipped() -> None:
    doc = {"markers": {0: {"x": "abc", "y": 2.0, "z": 3.0}, 2: {"x": 1.0, "y": 1.0, "z": 1.0}}}
    m, warnings = parse_marker_map(doc)
    assert set(m) == {2}
    assert len(warnings) == 1
    assert "marker 0" in warnings[0]


def test_none_and_empty_doc() -> None:
    assert parse_marker_map(None) == ({}, [])
    assert parse_marker_map({}) == ({}, [])
    assert parse_marker_map({"markers": None}) == ({}, [])


def test_markers_not_a_mapping() -> None:
    m, warnings = parse_marker_map({"markers": [1, 2, 3]})
    assert m == {}
    assert len(warnings) == 1
    assert "not a mapping" in warnings[0]
