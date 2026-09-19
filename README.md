# Maya Bridge

Lightweight CLI bridge that connects any AI code harness (Claude Code, OpenCode, Cursor, etc.) to live Autodesk Maya sessions.

## How It Works

```
┌─────────────┐                  ┌─────────────┐      TCP       ┌───────────┐
│ Claude Code  │   Bash tool      │  maya_bridge │◄──(Python)───►│   Maya    │
│ OpenCode     │──(CLI call)────►│    .py       │               │  (7001)   │
│ Cursor       │                  │              │◄──(Python)───►├───────────┤
│ ...          │                  │  argparse    │               │   Maya    │
└─────────────┘                  └─────────────┘               │  (7002)   │
                                                                └───────────┘
```

- **`maya_bridge_listener.py`** — runs inside Maya, registers the session
- **`maya_bridge.py`** — CLI tool, discovers Maya sessions and sends Python code to them
- **`maya_bridge_ui.py`** — PySide2 dockable panel showing session info and connected AI clients

Multiple Maya sessions supported simultaneously. Each instance gets a unique port (7001, 7002, ...).

## Requirements

- Python 3.9+ (no external packages needed)
- Maya 2023+

## Install

Run the installer and follow the prompts:

```
python install.py
```

The installer handles two steps — each is independently skippable:

1. **Skill installation** — global (`~/.claude/skills/`) or per-project (`.opencode/skills/`). Substitutes the bridge path into the skill template.
2. **`userSetup.py` patching** — shows exactly what will be added before writing

### Manual setup

#### 1. `userSetup.py`

Maya Bridge requires a Python commandPort opened **at Maya startup**. Maya 2023 has a bug where commandPorts opened after startup do not execute Python code.

Add the following to `~/Documents/maya/2023/scripts/userSetup.py`:

```python
import maya.cmds as cmds

def _mb_open_port(port, source_type):
    port_str = ':{}'.format(port)
    try:
        if not cmds.commandPort(port_str, query=True):
            cmds.commandPort(name=port_str, sourceType=source_type, echoOutput=False)
        return True
    except RuntimeError:
        return False

def _mb_open_port_auto(source_type, port_base=7001, port_max=7020):
    for port in range(port_base, port_max + 1):
        if _mb_open_port(port, source_type):
            return port
    return None

_mb_open_port_auto('python')
```

Each Maya instance gets its own port (7001, 7002, ...), supporting up to 20 simultaneous sessions.

#### 2. Skill

Copy `skill/SKILL.md` to your skill directory and replace `{{MAYA_BRIDGE_PATH}}` with the absolute path to `maya_bridge.py`:

- **Global:** `~/.claude/skills/maya-bridge/SKILL.md`
- **Per-project:** `.opencode/skills/maya-bridge/SKILL.md`

#### 3. Start the listener in Maya

Run in Maya's Python Script Editor:
```python
exec(open("<path/to/maya-bridge>/maya_bridge_listener.py").read())
```

This will:
- Find the commandPort opened by `userSetup.py` and register the session
- Add a shelf button to the current shelf (click to reopen the UI)
- Show a dockable panel with session info and connected AI clients

**Or install just the shelf button** (one-time setup):
```python
exec(open("<path/to/maya-bridge>/install_shelf_button.py").read())
```

## CLI Commands

```bash
# List active Maya sessions
python maya_bridge.py list

# Connect to a session
python maya_bridge.py connect 7001 --name "my session"

# Disconnect
python maya_bridge.py disconnect 7001

# Execute inline code
python maya_bridge.py eval --code "import maya.cmds; print(maya.cmds.ls(assemblies=True))"

# Execute a script file
python maya_bridge.py eval --file script.py

# Target a specific session
python maya_bridge.py eval --code "..." --session 7001
```

When only one Maya session exists, `--session` is optional.

### Example workflow

```
1. python maya_bridge.py list
   → [{"port": 7001, "scene": "hero_asset.mb", "connected": false},
      {"port": 7002, "scene": "rig_v2.mb",     "connected": false}]

2. python maya_bridge.py connect 7001 --name "Live Maya connection from chat"
   → "Connected to Maya session 7001 (hero_asset.mb, Maya 2023)"

3. python maya_bridge.py eval --code "import maya.cmds; print(maya.cmds.ls(assemblies=True))"
   → ['persp', 'top', 'front', 'side', 'VME_11208696']

4. python maya_bridge.py connect 7002 --name "Live Maya connection from chat"
   → now two sessions connected — must specify --session on eval

5. python maya_bridge.py eval --session 7001 --code "import maya.cmds; print(maya.cmds.file(q=True, sceneName=True))"
   → C:/scenes/hero_asset.mb
```

## Architecture

- **`sourceType="python"`** on Maya's commandPort — code sent as raw Python, no MEL wrapping
- **Fire-and-forget** — socket closed immediately after sending to avoid Maya 2023's CommandPort.py bytes/str bug; results written to temp files
- **Session registry** via temp files (`%TEMP%/maya_bridge_sessions/<port>.json`)
- **Client tracking** via heartbeat files (`%TEMP%/maya_bridge_clients/<port>_<client_id>.json`)
- **Persistent client ID** — stored in `%TEMP%/maya_bridge_clients/.client_id`, survives process restarts
- **Connection state** — file-based (`connections_<id>.json`), survives process exit
- **Watchdog timer** monitors port health and updates session metadata every 5 seconds
- **Stale cleanup** — dead sessions detected by PID check and removed automatically
- **Port collision detection** — listener skips already-registered ports so multiple Maya instances each get a unique port
