"""
Maya MCP Listener — run inside Maya to enable AI harness connections.

Opens a MEL commandPort on an auto-assigned port and registers
the session so MCP clients can discover and connect to it.
Creates a shelf button that opens a dockable UI panel.

Usage in Maya Script Editor (Python):
    exec(open("C:/Users/dkZuaAkb/Dev/Git/MayaMCP/maya_mcp_listener.py").read())
"""
import json
import os
import socket
import tempfile
import threading
import time

import maya.cmds as cmds
import maya.mel
import maya.utils

_SCRIPT_DIR = "C:/Users/dkZuaAkb/Dev/Git/MayaMCP"
PORT_BASE = 50007
PORT_MAX = 50099
SESSION_DIR = os.path.join(tempfile.gettempdir(), "maya_mcp_sessions")
ICON_PATH = os.path.join(_SCRIPT_DIR, "maya-mcp-icon.jpg")
SHELF_BUTTON_NAME = "mcpListener"
_active_port = None
_watchdog_active = False


# ── Port management ──


def _is_port_free(port):
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.5)
        s.bind(("127.0.0.1", port))
        s.close()
        return True
    except OSError:
        return False


def _find_free_port():
    for port in range(PORT_BASE, PORT_MAX + 1):
        session_file = os.path.join(SESSION_DIR, "{}.json".format(port))
        if os.path.exists(session_file):
            continue
        if _is_port_free(port):
            return port
    return None


def _check_port_alive(port):
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.5)
        s.bind(("127.0.0.1", port))
        s.close()
        return False
    except OSError:
        return True


def _open_port(port):
    port_name = ":{}".format(port)
    try:
        cmds.commandPort(port_name, close=True)
    except RuntimeError:
        pass
    cmds.commandPort(
        name=port_name,
        sourceType="mel",
        echoOutput=True,
        bufferSize=4096,
    )


# ── Session files ──


def _write_session_file(port):
    os.makedirs(SESSION_DIR, exist_ok=True)
    data = {
        "port": port,
        "pid": os.getpid(),
        "scene": cmds.file(q=True, sceneName=True) or "",
        "maya_version": cmds.about(version=True),
        "started": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    path = os.path.join(SESSION_DIR, "{}.json".format(port))
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def _update_session_file(port):
    path = os.path.join(SESSION_DIR, "{}.json".format(port))
    if not os.path.exists(path):
        _write_session_file(port)
        return
    try:
        with open(path) as f:
            data = json.load(f)
        data["scene"] = cmds.file(q=True, sceneName=True) or ""
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass


def _delete_session_file(port):
    path = os.path.join(SESSION_DIR, "{}.json".format(port))
    try:
        os.remove(path)
    except OSError:
        pass


# ── Watchdog ──


def _watchdog(port):
    if not _watchdog_active:
        return

    def _check():
        if not _check_port_alive(port):
            print("[MCP] Port {} died, reopening...".format(port))
            _open_port(port)
        _update_session_file(port)

    maya.utils.executeDeferred(_check)
    threading.Timer(5.0, _watchdog, args=[port]).start()


def _cleanup(port):
    global _watchdog_active
    _watchdog_active = False
    _delete_session_file(port)
    try:
        cmds.commandPort(":{}".format(port), close=True)
    except RuntimeError:
        pass


# ── Public API (called by UI) ──


def start_listener():
    global _watchdog_active, _active_port
    _watchdog_active = True

    if _active_port is not None and _check_port_alive(_active_port):
        print("[MCP] Already listening on port {}".format(_active_port))
        return

    port = _find_free_port()
    if port is None:
        cmds.warning("[MCP] No free port found in range {}-{}".format(PORT_BASE, PORT_MAX))
        return

    _open_port(port)
    _write_session_file(port)
    _active_port = port
    cmds.scriptJob(event=["quitApplication", lambda: _cleanup(port)])
    _watchdog(port)

    print("[MCP] Listening on port {} (sourceType=mel)".format(port))


def stop():
    global _active_port
    if _active_port is not None:
        _cleanup(_active_port)
        print("[MCP] Stopped listener on port {}".format(_active_port))
        _active_port = None
    else:
        print("[MCP] No active listener to stop")


# ── Shelf button ──


def _create_shelf_button():
    button_name = SHELF_BUTTON_NAME
    icon_path = ICON_PATH
    target_shelf = "Custom"
    shelf_top = maya.mel.eval("$tmpVar=$gShelfTopLevel")
    if not cmds.shelfLayout(target_shelf, exists=True):
        target_shelf = cmds.tabLayout(shelf_top, query=True, selectTab=True)

    existing = cmds.shelfLayout(target_shelf, query=True, childArray=True) or []
    for child in existing:
        if cmds.shelfButton(child, query=True, exists=True):
            try:
                if cmds.shelfButton(child, query=True, label=True) == button_name:
                    cmds.deleteUI(child)
            except RuntimeError:
                pass

    listener_path = os.path.join(_SCRIPT_DIR, "maya_mcp_listener.py").replace("\\", "/")
    click_cmd = (
        'import importlib.util, sys, maya.utils\n'
        'def _mcp_open():\n'
        '    if "maya_mcp_listener" in sys.modules: del sys.modules["maya_mcp_listener"]\n'
        '    spec = importlib.util.spec_from_file_location("maya_mcp_listener", "{path}")\n'
        '    mod = importlib.util.module_from_spec(spec)\n'
        '    spec.loader.exec_module(mod)\n'
        'maya.utils.executeDeferred(_mcp_open)\n'
    ).format(path=listener_path)

    kwargs = {
        "parent": target_shelf,
        "label": button_name,
        "annotation": "MCP Listener - connect AI harness to Maya",
        "command": click_cmd,
        "sourceType": "python",
    }
    if os.path.isfile(icon_path):
        kwargs["image"] = icon_path
        kwargs["imageOverlayLabel"] = ""
    else:
        kwargs["image"] = "pythonFamily.png"
        kwargs["imageOverlayLabel"] = "MCP"

    cmds.shelfButton(**kwargs)
    print("[MCP] Shelf button added to '{}'".format(target_shelf))


# ── Show UI ──


def _show_ui():
    ui_path = os.path.join(_SCRIPT_DIR, "maya_mcp_ui.py")
    if not os.path.isfile(ui_path):
        print("[MCP] UI module not found at {}".format(ui_path))
        return
    import importlib.util
    import sys
    mod_name = "maya_mcp_ui"
    if mod_name in sys.modules:
        del sys.modules[mod_name]
    spec = importlib.util.spec_from_file_location(mod_name, ui_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    listener_mod = sys.modules.get("maya_mcp_listener")
    mod.show(listener_module=listener_mod, icon_path=ICON_PATH)


# ── Entry point ──

import sys as _sys
import types as _types

# Register as a proper module so the UI can reference listener state
_mod = _types.ModuleType("maya_mcp_listener")
for _n in ["start_listener", "stop", "_active_port", "_check_port_alive",
           "_SCRIPT_DIR", "ICON_PATH", "SESSION_DIR", "CLIENT_DIR",
           "PORT_BASE", "PORT_MAX", "SHELF_BUTTON_NAME"]:
    if _n in globals():
        setattr(_mod, _n, globals()[_n])
_sys.modules["maya_mcp_listener"] = _mod

_create_shelf_button()
maya.utils.executeDeferred(_show_ui)
