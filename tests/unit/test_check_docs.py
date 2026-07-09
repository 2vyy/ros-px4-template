from __future__ import annotations

from pathlib import Path

import pytest

import check_docs


def test_extract_backticked_dedups_in_order() -> None:
    text = "Use `just sim`, then `marker_hover`, then `just sim` again."

    assert check_docs.extract_backticked(text) == ["just sim", "marker_hover"]


@pytest.mark.parametrize(
    ("token", "kind"),
    [
        ("src/core/x.py", "path"),
        ("just sim", "just"),
        ("marker_hover", "identifier"),
        ("/drone/odom", "topic"),
        ("unit", "skip"),
        ("--vision aruco", "skip"),
        ("<NN>_<name>", "skip"),
    ],
)
def test_classify_tokens(token: str, kind: str) -> None:
    assert check_docs.classify(token) == kind


def test_check_token_path_kind(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "node.py").write_text("pass\n", encoding="utf-8")

    assert check_docs.check_token("src/node.py", "path", tmp_path) is True
    assert check_docs.check_token("src/missing.py", "path", tmp_path) is False


def test_check_token_identifier_kind(tmp_path: Path) -> None:
    (tmp_path / "tools").mkdir()
    (tmp_path / "tools" / "x.py").write_text("marker_hover = True\n", encoding="utf-8")

    assert check_docs.check_token("marker_hover", "identifier", tmp_path) is True
    assert check_docs.check_token("doc_checker_missing_symbol", "identifier", tmp_path) is False


def test_main_reports_dead_identifier(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "AGENTS.md").write_text("Dead: `doc_checker_missing_symbol`\n", encoding="utf-8")
    (tmp_path / "justfile").write_text("sim:\n", encoding="utf-8")

    with pytest.raises(SystemExit) as exc:
        check_docs.main(["--root", str(tmp_path)])

    assert exc.value.code == 1
    assert "[FAIL] doc_checker_missing_symbol" in capsys.readouterr().out
