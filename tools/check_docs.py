#!/usr/bin/env python3
"""Conservative existence check for AGENTS.md backticked identifiers."""

from __future__ import annotations

import argparse
import re
import sys
from functools import cache
from pathlib import Path

_BACKTICK_RE = re.compile(r"`([^`\n]+)`")
_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]*$")
_RECIPE_RE = re.compile(r"^([A-Za-z][A-Za-z0-9_-]*)(?:\s.*)?:")
_PATH_SUFFIXES = {".py", ".md", ".yaml", ".toml", ".sdf", ".json", ".sh", ".rviz"}
_CORPUS_DIRS = ("src", "tools", "tests", "config", "sim", "hardware", "docs")
_CORPUS_FILES = ("justfile", "tasks.py")
_TEXT_SUFFIXES = _PATH_SUFFIXES | {".xml", ".txt"}

# Allowlist entries need a reason; these are external tokens, not repo symbols.
_ALLOWLIST = frozenset(
    {
        "C:\\",  # literal Windows path example in AGENTS.md
        # PX4 SITL build artifact under PX4_DIR (gitignored, not a repo file);
        # referenced in docs/SIM.md to explain the gz world-boot clobber.
        "build/px4_sitl_default/rootfs/gz_env.sh",
        # CodeGraph MCP tool name (external tooling, not a repo symbol);
        # referenced in the AGENTS.md Code intelligence section.
        "codegraph_explore",
    }
)

# Sub-commands of the typer sub-apps (add_typer in tasks.py; commands in
# tasks.py log_app, tools/capabilities.py, tools/mission_cli.py). A deliberate
# single-file hardcode: when a sub-app gains a command the docs check fails on
# the new doc line until this dict learns it. Cheap, visible, self-announcing.
_SUBCOMMANDS = {
    "log": {"summary", "tail", "topics", "since", "events"},
    "cap": {"show", "plan", "record"},
    "mission": {"list", "validate", "show", "sim", "schema"},
    "wait": {"ready", "run"},
    "sim": {"start"},
    "hw": {"start"},
}

# Docs an agent actually follows; each is scanned for backticked identifiers.
_DOC_FILES = ("AGENTS.md", "README.md")
# docs/*.md that intentionally name not-yet-existing things (a wishlist), so
# their backticked tokens are exempt from the existence check.
_DOC_EXCLUDE = frozenset({"BACKLOG.md"})


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
    if token in _ALLOWLIST or "<" in token or "[" in token or "*" in token or "&&" in token:
        return "skip"  # "<x>" and "[x]" are placeholder notation, not real tokens
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


@cache
def _recipes(root: Path) -> frozenset[str]:
    path = root / "justfile"
    if not path.is_file():
        return frozenset()
    recipes: set[str] = set()
    for raw in path.read_text(encoding="utf-8").splitlines():
        match = _RECIPE_RE.match(raw)
        if match is not None and not match.group(1).startswith("_"):
            recipes.add(match.group(1))
    return frozenset(recipes)


@cache
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
        stripped = _strip_fragment(token)
        if (root / stripped).exists():
            return True
        # Docs abbreviate src/core/ros_px4_template_core/{lib,nodes}/... as lib/... / nodes/...
        return (root / "src" / "core" / "ros_px4_template_core" / stripped).exists()
    if kind == "just":
        parts = token.split()
        if len(parts) < 2:
            return False
        if parts[1].startswith("-"):
            return True
        if parts[1] not in _recipes(root):
            return False
        # For a known sub-app, validate the second positional token (the
        # sub-command); flags and plain-recipe args stay exempt.
        subcmds = _SUBCOMMANDS.get(parts[1])
        if subcmds is not None and len(parts) > 2 and not parts[2].startswith("-"):
            return parts[2] in subcmds
        return True
    if kind in {"identifier", "topic"}:
        return token in _corpus_text(root)
    return True


def _doc_files(root: Path) -> list[Path]:
    """Docs an agent follows: AGENTS.md, README.md, and top-level docs/*.md
    (docs/superpowers/ is a subdir, so glob(*.md) already excludes it)."""
    files = [root / name for name in _DOC_FILES]
    docs = root / "docs"
    if docs.is_dir():
        files.extend(sorted(f for f in docs.glob("*.md") if f.name not in _DOC_EXCLUDE))
    return [f for f in files if f.is_file()]


def run(root: Path, verbose: bool = False) -> int:
    root = root.resolve()
    failed = 0
    checked = 0
    skipped = 0
    for doc in _doc_files(root):
        rel = doc.relative_to(root)
        for token in extract_backticked(doc.read_text(encoding="utf-8")):
            kind = classify(token)
            if kind == "skip":
                skipped += 1
                if verbose:
                    print(f"  [SKIP] {rel}: {token}")
                continue
            checked += 1
            if check_token(token, kind, root):
                if verbose:
                    print(f"  [OK]   {rel}: {token}")
            else:
                failed += 1
                print(f"  [FAIL] {rel}: {token} ({kind}): not found")

    if failed:
        print(f"Docs identifier check FAILED: {failed} failed, {checked} checked")
        return failed
    print(f"Docs identifier check OK: {checked} checked, {skipped} skipped.")
    return 0


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    if run(args.root, verbose=args.verbose) != 0:
        raise SystemExit(1)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
