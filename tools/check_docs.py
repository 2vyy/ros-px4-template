#!/usr/bin/env python3
"""Conservative existence check for AGENTS.md backticked identifiers."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

_BACKTICK_RE = re.compile(r"`([^`\n]+)`")
_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]*$")
_RECIPE_RE = re.compile(r"^([A-Za-z][A-Za-z0-9_-]*)(?:\s.*)?:")
_PATH_SUFFIXES = {".py", ".md", ".yaml", ".toml", ".sdf", ".json", ".sh", ".rviz"}
_CORPUS_DIRS = ("src", "tools", "tests", "config", "sim", "hardware", "docs")
_CORPUS_FILES = ("justfile", "tasks.py")
_TEXT_SUFFIXES = _PATH_SUFFIXES | {".xml", ".txt"}

# Allowlist entries need a reason; these are external tool names, not repo symbols.
_ALLOWLIST = frozenset(
    {
        "C:\\",  # literal Windows path example in AGENTS.md
        "search_graph",  # codebase-memory MCP tool
        "trace_path",  # codebase-memory MCP tool
        "get_code_snippet",  # codebase-memory MCP tool
        "query_graph",  # codebase-memory MCP tool
        "get_architecture",  # codebase-memory MCP tool
    }
)


def extract_backticked(text: str) -> list[str]:
    seen: set[str] = set()
    tokens: list[str] = []
    for match in _BACKTICK_RE.finditer(text):
        token = match.group(1).strip()
        if token and token not in seen:
            seen.add(token)
            tokens.append(token)
    return tokens


def _strip_fragment(token: str) -> str:
    return token.split("#", 1)[0]


def classify(token: str) -> str:
    if token in _ALLOWLIST or "<" in token or "*" in token or "&&" in token:
        return "skip"
    if token.startswith("just "):
        return "just"
    if token.startswith("/") and " " not in token:
        return "topic"
    if " " in token or "=" in token:
        return "skip"

    pathish = _strip_fragment(token)
    if "/" in pathish:
        suffix = Path(pathish).suffix
        if suffix in _PATH_SUFFIXES:
            return "path"
        return "skip"

    if _IDENT_RE.fullmatch(token) and "_" in token:
        return "identifier"
    return "skip"


def _recipes(root: Path) -> set[str]:
    path = root / "justfile"
    if not path.is_file():
        return set()
    recipes: set[str] = set()
    for raw in path.read_text(encoding="utf-8").splitlines():
        match = _RECIPE_RE.match(raw)
        if match is not None and not match.group(1).startswith("_"):
            recipes.add(match.group(1))
    return recipes


def _corpus_text(root: Path) -> str:
    chunks: list[str] = []
    for dirname in _CORPUS_DIRS:
        base = root / dirname
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            rel = path.relative_to(root)
            if rel.parts[:2] == ("docs", "superpowers"):
                continue
            if path.suffix not in _TEXT_SUFFIXES:
                continue
            try:
                chunks.append(path.read_text(encoding="utf-8"))
            except UnicodeDecodeError:
                continue
    for filename in _CORPUS_FILES:
        path = root / filename
        if path.is_file():
            chunks.append(path.read_text(encoding="utf-8"))
    return "\n".join(chunks)


def check_token(token: str, kind: str, root: Path) -> bool:
    if kind == "path":
        return (root / _strip_fragment(token)).exists()
    if kind == "just":
        parts = token.split()
        if len(parts) > 1 and parts[1].startswith("-"):
            return True
        return len(parts) > 1 and parts[1] in _recipes(root)
    if kind in {"identifier", "topic"}:
        return token in _corpus_text(root)
    return True


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    root = args.root.resolve()
    text = (root / "AGENTS.md").read_text(encoding="utf-8")
    failed = 0
    checked = 0
    skipped = 0
    for token in extract_backticked(text):
        kind = classify(token)
        if kind == "skip":
            skipped += 1
            if args.verbose:
                print(f"  [SKIP] {token}")
            continue
        checked += 1
        if check_token(token, kind, root):
            print(f"  [OK]   {token}")
        else:
            failed += 1
            print(f"  [FAIL] {token} ({kind}): not found")

    if failed:
        print(f"Docs identifier check FAILED: {failed} failed, {checked} checked")
        raise SystemExit(1)
    print(f"Docs identifier check OK: {checked} checked, {skipped} skipped.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
