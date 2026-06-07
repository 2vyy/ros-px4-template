#!/usr/bin/env python3
"""Shared, truthful command verdicts and fixed exit codes for the task CLI.

Commands speak concise English, not data formats. A success line is only ever
emitted by the caller AFTER post-conditions are verified, so these formatters
never imply success on their own. JSON stays in file artifacts, never here.
"""

from __future__ import annotations

from enum import IntEnum

_DEFAULT_LOG = "logs/latest.log"


class ExitCode(IntEnum):
    """Documented, fixed exit codes used by every task command."""

    OK = 0  # success / all post-conditions verified / all scenarios passed
    FAIL = 1  # operation ran but the result failed (build, NOT READY, scenario FAIL, e2e fails)
    USAGE = 2  # usage error (unknown command, unknown scenario, bad flag)
    PRECONDITION = 3  # preflight failure (port busy, PX4_DIR missing, ROS not sourced)


def format_ready(checks: list[str], elapsed_s: float, log: str = _DEFAULT_LOG) -> str:
    """Verdict for a stack that passed every readiness check."""
    return f"READY: {', '.join(checks)} - {elapsed_s:.1f}s ({log})"


def format_not_ready(reason: str, elapsed_s: float, log: str = _DEFAULT_LOG) -> str:
    """Verdict for a stack that failed to come up."""
    return f"NOT READY: {reason} after {elapsed_s:.0f}s (see {log})"


def format_scenario(name: str, passed: bool, detail: str, elapsed_s: float) -> str:
    """One rich line stating what a scenario actually verified."""
    tag = "PASS" if passed else "FAIL"
    return f"{tag} {name:<20} {detail:<48} {elapsed_s:>6.1f}s"


def format_stopped(killed: list[str], survivors: list[str]) -> str:
    """Verdict for a teardown. Survivors make the non-clean result visible."""
    if survivors:
        names = ", ".join(sorted(set(survivors)))
        return f"STOPPED WITH WARNINGS: {len(killed)} killed, survivors: {names}"
    return f"STOPPED: {len(killed)} processes killed, 0 survivors"


def format_e2e_block(rows: list[tuple[str, bool, str, float]]) -> str:
    """Aggregate scenario block: one rich line each, then a summary line."""
    lines = [format_scenario(n, p, d, e) for (n, p, d, e) in rows]
    n_pass = sum(1 for r in rows if r[1])
    n_fail = len(rows) - n_pass
    code = int(ExitCode.OK if n_fail == 0 else ExitCode.FAIL)
    lines.append("----")
    lines.append(f"{len(rows)} scenarios: {n_pass} PASS, {n_fail} FAIL  (exit {code})")
    return "\n".join(lines)
