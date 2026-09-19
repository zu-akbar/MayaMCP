---
name: maya-bridge
description: >
  Use when the user wants to connect to a live Maya session, automate Maya
  tasks, manipulate scene content, or access Maya tools like VME Tools via
  an AI harness. Do NOT use for general Maya questions or MEL/Python syntax
  help unrelated to a live session.
license: MIT
---

# Maya Bridge

You have access to a CLI bridge that connects to live Autodesk Maya sessions.
Use it to explore scenes, manipulate geometry, and automate Maya tools.

All commands use the Bash tool:

```
python "{{MAYA_BRIDGE_PATH}}" <subcommand> [options]
```

## Connection Workflow

Always follow this sequence at the start:

1. List available sessions:
   ```bash
   python "{{MAYA_BRIDGE_PATH}}" list
   ```

2. Ask the user which port(s) to connect to.

3. Connect:
   ```bash
   python "{{MAYA_BRIDGE_PATH}}" connect 7001 --name "Live Maya connection from chat"
   ```

4. When done:
   ```bash
   python "{{MAYA_BRIDGE_PATH}}" disconnect 7001
   ```

## Executing Code

Inline code:
```bash
python "{{MAYA_BRIDGE_PATH}}" eval --code "import maya.cmds; print(maya.cmds.ls(assemblies=True))"
```

Script file:
```bash
python "{{MAYA_BRIDGE_PATH}}" eval --file script.py
```

Explicit session (when multiple connected):
```bash
python "{{MAYA_BRIDGE_PATH}}" eval --code "..." --session 7001
```

## Multi-Session Rules

- When **one** session exists: `--session` is optional on eval calls.
- When **multiple** sessions are connected: always specify `--session PORT`.
- Each Maya instance gets its own port: 7001, 7002, etc.

## Output Handling

- Always use `print()` — results return to the AI, not Maya's Script Editor.
- `(no output)` means success with no return value — not an error.
- Timeout (15s) means Maya is busy or the commandPort is unresponsive.

```python
# Good
import maya.cmds; print(maya.cmds.ls(assemblies=True))

# Bad — no output returned
import maya.cmds; maya.cmds.ls(assemblies=True)
```

## Scene Exploration

```python
# Scene file path
import maya.cmds; print(maya.cmds.file(q=True, sceneName=True))

# All DAG nodes
import maya.cmds; print(maya.cmds.ls(dag=True))

# Top-level assemblies only
import maya.cmds; print(maya.cmds.ls(assemblies=True))

# All meshes
import maya.cmds; print(maya.cmds.ls(type='mesh'))

# All materials
import maya.cmds; print(maya.cmds.ls(materials=True))

# Bounding box of an object
import maya.cmds; print(maya.cmds.xform('pCube1', q=True, ws=True, bb=True))
```

## Geometry Manipulation

```python
# Create
import maya.cmds; maya.cmds.polyCube(w=100, h=100, d=100, n='myCube')
import maya.cmds; maya.cmds.polySphere(r=50, n='mySphere')
import maya.cmds; maya.cmds.polyPlane(w=100, h=100, sx=1, sy=1, n='myPlane')

# Move / rotate / scale
import maya.cmds; maya.cmds.move(0, 50, 0, 'myCube')
import maya.cmds; maya.cmds.rotate(0, 45, 0, 'myCube')
import maya.cmds; maya.cmds.scale(2, 2, 2, 'myCube')

# Delete
import maya.cmds; maya.cmds.delete('myCube')

# Select
import maya.cmds; maya.cmds.select('myCube')
```

## Tool Discovery

To find the command behind any shelf button:

```python
import maya.cmds, maya.mel
shelf_top = maya.mel.eval('$tmp=$gShelfTopLevel')
buttons = maya.cmds.shelfLayout('LEGO_DWF', q=True, childArray=True) or []
for btn in buttons:
    try:
        label = maya.cmds.shelfButton(btn, q=True, label=True)
        ann = maya.cmds.shelfButton(btn, q=True, annotation=True)
        cmd = maya.cmds.shelfButton(btn, q=True, command=True)
        print(f"{label} | {ann}\n  {cmd}\n")
    except:
        pass
```

## LEGO Tools

### VME Tools
```python
import iVMEb; from iVMEb import VMEFlowTool; iVMEb.VMEFlowTool.load()
```

### VME Tools (Digital Only)
```python
# Use annotation "VME Tools for Digital Only" button on LEGO_DWF shelf
# Discover its command via the Tool Discovery pattern above
```

### Export Styles
```python
# Use annotation "Export Styles" button on LEGO_DWF shelf
```

### Crease Tool
```python
# Use annotation "Crease Tool" button on LEGO_DWF shelf
```

### Toggle Edges
```python
# Use annotation "Toggle Edges" button on LEGO_DWF shelf
```

### Generic: Run any LEGO_DWF shelf tool by annotation
```python
import maya.cmds, maya.mel
def run_dwf_tool(annotation):
    shelf_top = maya.mel.eval('$tmp=$gShelfTopLevel')
    for btn in maya.cmds.shelfLayout('LEGO_DWF', q=True, childArray=True) or []:
        try:
            if maya.cmds.shelfButton(btn, q=True, annotation=True) == annotation:
                cmd = maya.cmds.shelfButton(btn, q=True, command=True)
                exec(cmd)
                return
        except:
            pass
    print(f"Tool not found: {annotation}")

run_dwf_tool('Export Styles')
```

---

> **Note:** The LEGO tools section grows over time — add new tools and their
> commands here as they are discovered.
