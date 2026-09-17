# Maya MCP Server

Lightweight MCP server that connects any AI code harness (Claude Code, OpenCode, Cursor, etc.) to live Autodesk Maya sessions.

## How It Works

```
┌─────────────┐      stdio       ┌─────────────┐      TCP       ┌───────────┐
│ Claude Code  │◄───(JSON-RPC)───►│  MCP Server  │◄──(Python)───►│   Maya    │
│ OpenCode     │                  │              │               │  (50007)  │
│ Cursor       │                  │ maya_mcp_    │               ├───────────┤
│ ...          │                  │ server.py    │◄──(Python)───►│   Maya    │
└─────────────┘                  └─────────────┘               │  (50008)  │
                                                                └───────────┘
```

- **`maya_mcp_listener.py`** — runs inside Maya, opens a Python commandPort and registers the session
- **`maya_mcp_server.py`** — MCP server (stdio), discovers Maya sessions and sends Python code to them
- **`maya_mcp_ui.py`** — PySide2 dialog showing session info and connected AI clients

Multiple Maya sessions supported simultaneously. Each gets a unique port and session ID.

## Setup

No external dependencies — the MCP protocol is implemented directly. Requires Python 3.9+.

### 1. Register the MCP server with your AI harness

**Claude Code** — add `.mcp.json` to your project root:
```json
{
  "mcpServers": {
    "maya": {
      "command": "python",
      "args": ["C:/path/to/MayaMCP/maya_mcp_server.py"]
    }
  }
}
```

**Other MCP clients** — point to `python` + `maya_mcp_server.py` via stdio transport.

### 3. Start the listener in Maya

Run in Maya's Python Script Editor:
```python
exec(open("C:/path/to/MayaMCP/maya_mcp_listener.py").read())
```

This will:
- Open a Python commandPort on an auto-assigned port (50007-50099)
- Register the session for MCP discovery
- Add a shelf button to the current shelf (click to reopen the UI)
- Show a status dialog with session info and connected clients

**Or install just the shelf button** (one-time setup):
```python
exec(open("C:/path/to/MayaMCP/install_shelf_button.py").read())
```

## MCP Tools

### Discovery & Connection

| Tool | Description |
|------|-------------|
| `maya_list_sessions` | List all active Maya sessions — shows port, scene, version, and connection status |
| `maya_connect` | Bind a Maya session to this chat session |
| `maya_disconnect` | Unbind a Maya session from this chat session |

### Execution

| Tool | Description |
|------|-------------|
| `maya_eval` | Execute Python code in a connected Maya session |
| `maya_eval_file` | Execute a .py script file in a connected Maya session |

When only one Maya session is connected, `session_id` is optional on eval calls.

### Example workflow

```
1. maya_list_sessions()
   → [{"port": 50007, "scene": "hero_asset.mb", "connected": false}, ...]

2. maya_connect(session_id="50007")
   → "Connected to Maya session 50007 (hero_asset.mb, Maya 2023)"

3. maya_eval(code="import maya.cmds; maya.cmds.ls(assemblies=True)")
   → "['persp', 'top', 'front', 'side', 'VME_11208696']"
   (no session_id needed — only one connected)

4. maya_connect(session_id="50008")
   → now two sessions connected — must specify session_id on eval

5. maya_eval(session_id="50007", code="maya.cmds.file(q=True, sceneName=True)")
   → "C:/scenes/hero_asset.mb"
```

## Architecture

- **`sourceType="python"`** on Maya's commandPort — code sent as raw Python, no MEL wrapping
- **Session registry** via temp files (`%TEMP%/maya_mcp_sessions/<port>.json`)
- **Client tracking** via heartbeat files (`%TEMP%/maya_mcp_clients/<port>_<client_id>.json`)
- **Watchdog timer** auto-reopens the port if Maya drops it
- **Stale cleanup** — dead sessions/clients detected by PID check and removed automatically

## Requirements

- Python 3.9+ (no external packages needed)
- Maya 2023+ (code sent to Maya must be compatible with Maya's Python version)
