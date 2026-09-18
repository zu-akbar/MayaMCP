# Maya MCP Server

Lightweight MCP server that connects any AI code harness (Claude Code, OpenCode, Cursor, etc.) to live Autodesk Maya sessions.

## How It Works

```
┌─────────────┐      stdio       ┌─────────────┐      TCP       ┌───────────┐
│ Claude Code  │◄───(JSON-RPC)───►│  MCP Server  │◄──(Python)───►│   Maya    │
│ OpenCode     │                  │              │               │  (7001)   │
│ Cursor       │                  │ maya_mcp_    │               ├───────────┤
│ ...          │                  │ server.py    │◄──(Python)───►│   Maya    │
└─────────────┘                  └─────────────┘               │  (7002)   │
                                                                └───────────┘
```

- **`maya_mcp_listener.py`** — runs inside Maya, registers the session with the MCP server
- **`maya_mcp_server.py`** — MCP server (stdio), discovers Maya sessions and sends Python code to them
- **`maya_mcp_ui.py`** — PySide2 dockable panel showing session info and connected AI clients

Multiple Maya sessions supported simultaneously. Each instance gets a unique port (7001, 7002, ...).

## Requirements

- Python 3.9+ (no external packages needed)
- Maya 2023+

## Setup

### 1. Configure `userSetup.py`

The listener relies on Python commandPorts opened **at Maya startup** via `userSetup.py`. Maya 2023 has a bug where commandPorts opened after startup do not execute Python code.

Add the following to `~/Documents/maya/2023/scripts/userSetup.py`:

```python
import maya.cmds as cmds

def open_command_port(port, source_type):
    port_str = ':{}'.format(port)
    try:
        if not cmds.commandPort(port_str, query=True):
            cmds.commandPort(name=port_str, sourceType=source_type, echoOutput=False)
        return True
    except RuntimeError:
        return False

def open_command_port_auto(source_type, port_base=7001, port_max=7020):
    for port in range(port_base, port_max + 1):
        if open_command_port(port, source_type):
            return port
    return None

open_command_port_auto('python')
```

This opens the first available port in the range **7001–7020** at startup. Each Maya instance gets its own port (7001, 7002, etc.), supporting up to 20 simultaneous sessions.

### 2. Register the MCP server with your AI harness

**OpenCode (global)** — add to `~/.config/opencode/opencode.json`:
```json
{
  "mcp": {
    "maya": {
      "type": "local",
      "command": ["python", "C:/path/to/MayaMCP/maya_mcp_server.py"],
      "enabled": true
    }
  }
}
```

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
- Find the commandPort opened by `userSetup.py` and register the session
- Add a shelf button to the current shelf (click to reopen the UI)
- Show a dockable panel with session info and connected AI clients

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
   → [{"port": 7001, "scene": "hero_asset.mb", "connected": false},
      {"port": 7002, "scene": "rig_v2.mb",     "connected": false}]

2. maya_connect(session_id="7001", session_name="Asset Rigging")
   → "Connected to Maya session 7001 (hero_asset.mb, Maya 2023)"

3. maya_eval(code="import maya.cmds; maya.cmds.ls(assemblies=True)")
   → "['persp', 'top', 'front', 'side', 'VME_11208696']"
   (no session_id needed — only one connected)

4. maya_connect(session_id="7002", session_name="Asset Rigging")
   → now two sessions connected — must specify session_id on eval

5. maya_eval(session_id="7001", code="maya.cmds.file(q=True, sceneName=True)")
   → "C:/scenes/hero_asset.mb"
```

## Architecture

- **`sourceType="python"`** on Maya's commandPort — code sent as raw Python, no MEL wrapping
- **Fire-and-forget** — socket closed immediately after sending to avoid Maya 2023's CommandPort.py bytes/str bug; results written to temp files
- **Session registry** via temp files (`%TEMP%/maya_mcp_sessions/<port>.json`)
- **Client tracking** via heartbeat files (`%TEMP%/maya_mcp_clients/<port>_<client_id>.json`)
- **Watchdog timer** monitors port health and updates session metadata every 5 seconds
- **Stale cleanup** — dead sessions/clients detected by PID check and removed automatically
- **Port collision detection** — listener skips already-registered ports so multiple Maya instances each get a unique port
