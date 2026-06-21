"""Unit tests for check_topics: dry-run (source grep) mode and live
manifest-row parsing / type+direction verdicts."""

from __future__ import annotations

from pathlib import Path

from check_topics import TopicSpec, _topics_in_source, check_spec, parse_manifest


def test_finds_topic_in_source(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    (src / "node.py").write_text(
        'self.create_publisher(PoseStamped, "/drone/target_pose", qos)\n',
        encoding="utf-8",
    )
    found = _topics_in_source(["/drone/target_pose", "/missing/topic"], [src])
    assert "/drone/target_pose" in found
    assert "/missing/topic" not in found


def test_returns_empty_when_no_source_files(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    found = _topics_in_source(["/some/topic"], [empty])
    assert found == set()


def test_searches_nested_directories(tmp_path: Path) -> None:
    nested = tmp_path / "src" / "core" / "nodes"
    nested.mkdir(parents=True)
    (nested / "ctrl.py").write_text('"/fmu/in/trajectory_setpoint"', encoding="utf-8")
    found = _topics_in_source(["/fmu/in/trajectory_setpoint"], [tmp_path / "src"])
    assert "/fmu/in/trajectory_setpoint" in found


def test_nonexistent_source_root_is_skipped(tmp_path: Path) -> None:
    missing_dir = tmp_path / "does_not_exist"
    found = _topics_in_source(["/drone/pose_enu"], [missing_dir])
    assert found == set()


_MANIFEST = """\
## Topics

| Topic | Type | Dir | Owner |
|-------|------|-----|-------|
| `/clock` | `rosgraph_msgs/msg/Clock` | pub | clock_bridge |
| `/drone/odom` | `nav_msgs/msg/Odometry` | pub/sub | position_node |

### Subscriptions

| Topic | Subscribers |
|-------|-------------|
| `/clock` | `offboard_controller` |
"""


def test_parse_manifest_returns_specs_for_four_column_rows() -> None:
    specs = parse_manifest(_MANIFEST)
    assert TopicSpec("/clock", "rosgraph_msgs/msg/Clock", "pub") in specs
    assert TopicSpec("/drone/odom", "nav_msgs/msg/Odometry", "pub/sub") in specs
    assert len(specs) == 2


def test_parse_manifest_skips_subscriptions_table_and_headers() -> None:
    specs = parse_manifest(_MANIFEST)
    names = [s.name for s in specs]
    # The Subscriptions table's "Topic | Subscribers" row is 2-column and
    # must not produce a duplicate /clock spec or a "Subscribers" name.
    assert names.count("/clock") == 1
    assert "Subscribers" not in names
    assert "Topic" not in names


def test_check_spec_happy_path_returns_no_problems() -> None:
    spec = TopicSpec("/clock", "rosgraph_msgs/msg/Clock", "pub")
    problems = check_spec(spec, "rosgraph_msgs/msg/Clock", pub=1, sub=0)
    assert problems == []


def test_check_spec_type_mismatch_mentions_both_types() -> None:
    spec = TopicSpec("/clock", "rosgraph_msgs/msg/Clock", "pub")
    problems = check_spec(spec, "std_msgs/msg/Header", pub=1, sub=0)
    assert len(problems) == 1
    assert "rosgraph_msgs/msg/Clock" in problems[0]
    assert "std_msgs/msg/Header" in problems[0]


def test_check_spec_declared_pub_with_no_publisher() -> None:
    spec = TopicSpec("/clock", "rosgraph_msgs/msg/Clock", "pub")
    problems = check_spec(spec, "rosgraph_msgs/msg/Clock", pub=0, sub=0)
    assert "declared pub but no publisher" in problems


def test_check_spec_observed_type_none_is_not_present() -> None:
    spec = TopicSpec("/clock", "rosgraph_msgs/msg/Clock", "pub")
    problems = check_spec(spec, None, pub=0, sub=0)
    assert problems == ["not present on the live graph"]
