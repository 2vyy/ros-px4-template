#!/usr/bin/env python3
"""Live capture filter: tag src=, relativize t=, collapse consecutive duplicates.

Reads the ros2 launch combined stdout (one line at a time) and writes the canonical
logfmt session log. Our nodes embed an absolute ``t=<epoch>``; third-party lines get
an arrival timestamp. Source is the ros2 launch ``[proc-N]`` prefix. The only
reduction is lossless consecutive-identical collapse, so a smoking gun is never hidden.
"""

from __future__ import annotations

import re
import sys
import time

_PREFIX = re.compile(r"^\[([^\]]+?)-\d+\]\s?(.*)$")
_TVAL = re.compile(r"^t=(\d+(?:\.\d+)?)\s?(.*)$")


def split_prefix(line: str) -> tuple[str | None, str]:
    """Split a ros2 launch ``[name-N] rest`` prefix into ``(name, rest)``."""
    m = _PREFIX.match(line)
    if m:
        return m.group(1), m.group(2)
    return None, line


class Capturer:
    """Streaming transform with consecutive-identical dedup."""

    def __init__(self) -> None:
        self._t0: float | None = None
        self._pending: str | None = None  # payload (src + body), no t=
        self._pending_t: float = 0.0
        self._count = 0

    def _emit_pending(self) -> list[str]:
        if self._pending is None:
            return []
        suffix = f" (x{self._count})" if self._count > 1 else ""
        line = f"t={self._pending_t:.3f} {self._pending}{suffix}"
        self._pending = None
        self._count = 0
        return [line]

    def feed(self, raw: str, now: float) -> list[str]:
        raw = raw.rstrip("\n")
        if not raw.strip():
            return []
        src, rest = split_prefix(raw)
        m = _TVAL.match(rest)
        if m:
            epoch = float(m.group(1))
            rest = m.group(2)
        else:
            epoch = now
        if self._t0 is None:
            self._t0 = epoch
        t_rel = max(0.0, epoch - self._t0)
        payload = f"src={src or 'unknown'} {rest}".rstrip()

        out: list[str] = []
        if payload == self._pending:
            self._count += 1
            # _pending_t stays at the first occurrence's timestamp
        else:
            out = self._emit_pending()
            self._pending = payload
            self._pending_t = t_rel
            self._count = 1
        return out

    def flush(self) -> list[str]:
        return self._emit_pending()


def main() -> None:
    cap = Capturer()
    # readline (not ``for raw in sys.stdin``) avoids block-buffering on a pipe, so
    # live capture writes promptly and third-party arrival stamps stay accurate.
    for raw in iter(sys.stdin.readline, ""):
        for line in cap.feed(raw, time.time()):
            print(line, flush=True)
    for line in cap.flush():
        print(line, flush=True)


if __name__ == "__main__":
    main()
