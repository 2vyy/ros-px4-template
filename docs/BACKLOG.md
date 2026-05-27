# Backlog

Tracked ideas pulled out of the README. Status: `idea` | `explore` | `decide` | `done`.

| ID | Idea | Status | Notes |
|----|------|--------|-------|
| B1 | Auto-debug or richer guidance when `check_invariants` or scenarios fail | explore | Was an inline TODO on the invariants bullet |
| B2 | Review structured JSONL merge (`just merge-logs`); dedupe or compress very large logs | explore | Feature exists in `tools/log_merger.py`; needs evaluation on real runs |
| B3 | `just` recipe or tools script for prerequisite checks (ROS, PX4 path, ports 8888 and 9090) | done | `just preflight` via `tools/preflight.py`; `just wait-ready` via `tools/wait_ready.py`; `just e2e` orchestrates full headless cycle; `just clean-logs` resets per-run JSONL |
| B4 | Avoid duplicating justfile recipes in README | done | README points at `just --list` |
| B5 | `demo-inspect` versus `sim-inspect` | done | `demo-inspect` is sim plus vision in background plus RViz; `sim-inspect` is sim only. See [MISSIONS.md](MISSIONS.md) |
| B6 | Trim Launch split and Config layering in README | done | One sentence each in README |
| B7 | Document `uv` at repo root (`pyproject.toml` dev deps) and port checklist for sim and MCP | idea | Ports: MicroXRCE 8888, rosbridge 9090 |
