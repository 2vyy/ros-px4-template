"""Unit tests for check_topics: dry-run (source grep) mode and live
manifest-row parsing / type+direction verdicts."""

from __future__ import annotations

import subprocess
from pathlib import Path

import check_topics
from check_topics import (
    TopicSpec,
    _query_live_topics,
    _topics_in_source,
    check_spec,
    parse_manifest,
    should_enforce,
)


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


_VISION_MANIFEST = """\
## Topics

| Topic | Type | Dir | Owner |
|-------|------|-----|-------|
| `/clock` | `rosgraph_msgs/msg/Clock` | pub | clock_bridge |
| `/drone/marker_detection` | `px4_ros_msgs/msg/MarkerDetection` | pub (vision) | aruco_pub |
"""


def test_parse_manifest_marks_vision_row_as_conditional() -> None:
    specs = parse_manifest(_VISION_MANIFEST)
    vision_spec = next(s for s in specs if s.name == "/drone/marker_detection")
    assert vision_spec.direction == "pub"
    assert vision_spec.conditional is True


def test_parse_manifest_plain_row_is_not_conditional() -> None:
    specs = parse_manifest(_VISION_MANIFEST)
    plain_spec = next(s for s in specs if s.name == "/clock")
    assert plain_spec.conditional is False


def test_should_enforce_skips_conditional_topic_when_vision_off() -> None:
    spec = TopicSpec("/drone/marker_detection", "px4_ros_msgs/msg/MarkerDetection", "pub", True)
    assert should_enforce(spec, vision=False) is False


def test_should_enforce_enforces_conditional_topic_when_vision_on() -> None:
    spec = TopicSpec("/drone/marker_detection", "px4_ros_msgs/msg/MarkerDetection", "pub", True)
    assert should_enforce(spec, vision=True) is True


def test_should_enforce_always_enforces_plain_topic() -> None:
    spec = TopicSpec("/clock", "rosgraph_msgs/msg/Clock", "pub")
    assert should_enforce(spec, vision=False) is True


def test_query_live_topics_parses_verbose_topic_list(monkeypatch) -> None:
    stdout = """
Published topics:
 * /drone/odom [nav_msgs/msg/Odometry] 1 publisher
 * /clock [rosgraph_msgs/msg/Clock] 2 publishers

Subscribed topics:
 * /drone/odom [nav_msgs/msg/Odometry] 1 subscriber
 * /fmu/in/trajectory_setpoint [px4_msgs/msg/TrajectorySetpoint] 1 subscriber
"""
    calls: list[list[str]] = []

    def fake_run(args: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        assert kwargs == {"capture_output": True, "text": True}
        return subprocess.CompletedProcess(args, 0, stdout=stdout)

    monkeypatch.setattr(check_topics.subprocess, "run", fake_run)

    info = _query_live_topics()

    assert calls == [["ros2", "topic", "list", "--verbose"]]
    assert info["/drone/odom"] == ("nav_msgs/msg/Odometry", 1, 1)
    assert info["/clock"] == ("rosgraph_msgs/msg/Clock", 2, 0)
    assert info["/fmu/in/trajectory_setpoint"] == ("px4_msgs/msg/TrajectorySetpoint", 0, 1)
    assert "/missing/topic" not in info


def test_query_live_topics_handles_subprocess_failure(monkeypatch) -> None:
    def fake_run(args: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
        assert args == ["ros2", "topic", "list", "--verbose"]
        assert kwargs == {"capture_output": True, "text": True}
        return subprocess.CompletedProcess(args, 1, stdout="")

    monkeypatch.setattr(check_topics.subprocess, "run", fake_run)

    assert _query_live_topics() == {}
