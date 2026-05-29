# MCP (ros-mcp)

## Prerequisite

[ros-mcp-server](https://github.com/robotmcp/ros-mcp-server).

**ROS (apt):** `ros-jazzy-rosbridge-suite` in the same environment that runs `just sim` (distrobox `ubuntu` on CachyOS). Project Python tools use **`uv sync`**, not pip.

Rosbridge WebSocket on port **9090**. It is launched by `hardware/launch/hardware.launch.py`, which is included by `sim/launch/sim_full.launch.py`. So both `just sim` and `just hardware` bring it up.

Check the port (do not point HTTP `curl` at the WebSocket endpoint):

```bash
ss -tlnp | grep 9090
# or
nc -z 127.0.0.1 9090
```

Startup order for the full stack: [README §Quick start](../README.md#quick-start).

## Cursor config

File: `.cursor/mcp.json` (not a repo-root `.mcp.json`).

```json
{
  "mcpServers": {
    "ros-mcp": {
      "type": "stdio",
      "command": "/absolute/path/from/which-uvx",
      "args": ["ros-mcp", "--transport=stdio"]
    }
  }
}
```

Set `command` to the literal output of `which uvx` on the **same machine that runs rosbridge**. `${userHome}` inside `command` breaks the path.

### WSL / split OS

Open the repo in WSL and use the WSL `uvx` path. If the IDE runs on Windows but rosbridge runs in WSL, a Windows `uvx` path will not work: the MCP client and rosbridge need one OS view of the filesystem and network.

For invoking `just` from a Windows shell when the repo lives on `C:\`, see [AGENTS.md §Where to run](../AGENTS.md#where-to-run).

## Ports

| Port | Service | Started by |
|------|---------|------------|
| 8888 | MicroXRCEAgent (UDP4) | `sim/launch/sim_full.launch.py` |
| 9090 | rosbridge WebSocket | `hardware/launch/hardware.launch.py` |

## Typical session

1. `just sim`. Wait until `/fmu/out/*` topics appear (a few minutes for PX4 boot, EKF2, preflight).
2. Connect MCP to `127.0.0.1:9090`.
3. On failure: [AGENTS.md §MCP / logs](../AGENTS.md#mcp--logs).
