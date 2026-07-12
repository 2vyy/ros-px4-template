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
        ("just test [type]", "skip"),  # [x] is placeholder notation, like <x>
    ],
)
def test_classify_tokens(token: str, kind: str) -> None:
    assert check_docs.classify(token) == kind


def _justfile(tmp_path: Path, *recipes: str) -> Path:
    (tmp_path / "justfile").write_text("".join(f"{r}:\n" for r in recipes), encoding="utf-8")
    return tmp_path


def test_check_token_validates_subcommands(tmp_path: Path) -> None:
    root = _justfile(tmp_path, "log", "sim")
    assert check_docs.check_token("just log tail", "just", root) is True
    assert check_docs.check_token("just log frobnicate", "just", root) is False
    assert check_docs.check_token("just sim --gui", "just", root) is True  # flag, not a subcmd
    assert check_docs.check_token("just ghost", "just", root) is False  # unknown recipe


def test_check_token_path_resolves_src_abbreviation(tmp_path: Path) -> None:
    pkg = tmp_path / "src" / "core" / "ros_px4_template_core" / "lib"
    pkg.mkdir(parents=True)
    (pkg / "frames.py").write_text("pass\n", encoding="utf-8")
    assert check_docs.check_token("lib/frames.py", "path", tmp_path) is True
    assert check_docs.check_token("lib/ghost.py", "path", tmp_path) is False


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
    assert "[FAIL] AGENTS.md: doc_checker_missing_symbol" in capsys.readouterr().out


def test_main_attributes_failure_to_the_right_doc(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "AGENTS.md").write_text("clean doc\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("Dead: `doc_checker_missing_symbol`\n", encoding="utf-8")
    (tmp_path / "justfile").write_text("sim:\n", encoding="utf-8")

    with pytest.raises(SystemExit) as exc:
        check_docs.main(["--root", str(tmp_path)])

    assert exc.value.code == 1
    assert "[FAIL] README.md: doc_checker_missing_symbol" in capsys.readouterr().out
