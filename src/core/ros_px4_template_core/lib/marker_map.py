"""Pure parsing of a marker-map document into {marker_id: (x, y, z)} (ENU).

`rclpy`-free so it is unit-testable without a ROS graph. The parse never raises
on bad input: a malformed entry is skipped and reported in the returned warnings
list, so the node can log it instead of dying in `__init__`.
"""

from __future__ import annotations


def parse_marker_map(
    doc: dict | None,
) -> tuple[dict[int, tuple[float, float, float]], list[str]]:
    """Turn a loaded marker-map document into ``(map, warnings)``.

    Args:
        doc: The YAML document (or ``None``), expected to carry a ``markers``
            mapping of ``id -> {x, y, z}``.

    Returns:
        ``(map, warnings)`` where ``map`` is ``{int id: (x, y, z) float ENU}`` and
        ``warnings`` holds one human-readable string per skipped malformed entry.
        Never raises on bad input.
    """
    out: dict[int, tuple[float, float, float]] = {}
    warnings: list[str] = []
    markers = (doc or {}).get("markers") or {}
    if not isinstance(markers, dict):
        return ({}, [f"'markers' is not a mapping: {type(markers).__name__}"])
    for k, v in markers.items():
        try:
            mid = int(k)
            x, y, z = float(v["x"]), float(v["y"]), float(v["z"])
        except (KeyError, TypeError, ValueError) as e:
            warnings.append(f"marker {k!r}: {type(e).__name__}: {e}")
            continue
        out[mid] = (x, y, z)
    return (out, warnings)
