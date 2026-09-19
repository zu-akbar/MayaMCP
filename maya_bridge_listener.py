"""
Maya Bridge Listener — run inside Maya to enable AI harness connections.

Opens a MEL commandPort on an auto-assigned port and registers
the session so CLI bridge clients can discover and connect to it.
Creates a shelf button that opens a dockable UI panel.

Usage in Maya Script Editor (Python):
    exec(open("C:/Users/dkZuaAkb/Dev/Git/maya-bridge/maya_bridge_listener.py").read())
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

_SCRIPT_DIR = "C:/Users/dkZuaAkb/Dev/Git/maya-bridge"
DEFAULT_PORT = 7001
PORT_MAX = 7020  # Must match userSetup.py open_command_port_auto range
SESSION_DIR = os.path.join(tempfile.gettempdir(), "maya_bridge_sessions")
ICON_PATH = os.path.join(_SCRIPT_DIR, "maya-bridge-icon.jpg")
SHELF_BUTTON_NAME = "mayaBridge"
_active_port = None
_watchdog_active = False


# ── Port management ──


def _check_port_alive(port):
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.5)
        s.bind(("127.0.0.1", port))
        s.close()
        return False
    except OSError:
        return True


def _find_open_port():
    """Find an already-open Python commandPort.

    Maya 2023 has a bug where commandPorts opened after startup don't
    execute code (CommandPort.py bytes/str bug). Ports opened during
    startup via userSetup.py work fine. We look for those.
    
    Also checks if a session file already exists for that port (from another Maya instance)
    and skips it to avoid collisions.
    """
    os.makedirs(SESSION_DIR, exist_ok=True)

    for port in range(DEFAULT_PORT, PORT_MAX + 1):
        if _check_port_alive(port):
            # Skip if another Maya instance already registered on this port
            session_file = os.path.join(SESSION_DIR, "{}.json".format(port))
            if not os.path.exists(session_file):
                return port
    return None


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
    if not _watchdog_active or _active_port is None:
        return

    def _check():
        if _active_port is None:
            return
        if not _check_port_alive(port):
            print("[Maya Bridge] Port {} no longer available".format(port))
        _update_session_file(port)

    maya.utils.executeDeferred(_check)
    threading.Timer(5.0, _watchdog, args=[port]).start()


# ── Public API (called by UI) ──


def start_listener():
    global _watchdog_active, _active_port

    if _active_port is not None:
        print("[Maya Bridge] Already registered on port {}".format(_active_port))
        return

    port = _find_open_port()
    if port is None:
        cmds.warning("[Maya Bridge] No open Python commandPort found. "
                     "Ensure userSetup.py opens one (e.g. port 7001).")
        return

    _watchdog_active = True
    _write_session_file(port)
    _active_port = port
    cmds.scriptJob(event=["quitApplication", lambda: stop()])
    _watchdog(port)

    print("[Maya Bridge] Registered on port {} (existing commandPort)".format(port))


def stop():
    global _active_port, _watchdog_active
    port = _active_port
    if port is not None:
        _watchdog_active = False
        _active_port = None
        _delete_session_file(port)
        print("[Maya Bridge] Unregistered from port {}".format(port))
    else:
        print("[Maya Bridge] Not registered")


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

    listener_path = os.path.join(_SCRIPT_DIR, "maya_bridge_listener.py").replace("\\", "/")
    click_cmd = (
        'import importlib.util, sys, maya.utils\n'
        'def _bridge_open():\n'
        '    if "maya_bridge_listener" in sys.modules: del sys.modules["maya_bridge_listener"]\n'
        '    spec = importlib.util.spec_from_file_location("maya_bridge_listener", "{path}")\n'
        '    mod = importlib.util.module_from_spec(spec)\n'
        '    sys.modules["maya_bridge_listener"] = mod\n'
        '    spec.loader.exec_module(mod)\n'
        'maya.utils.executeDeferred(_bridge_open)\n'
    ).format(path=listener_path)

    kwargs = {
        "parent": target_shelf,
        "label": button_name,
        "annotation": "Maya Bridge - connect AI harness to Maya",
        "command": click_cmd,
        "sourceType": "python",
    }
    if os.path.isfile(icon_path):
        kwargs["image"] = icon_path
        kwargs["imageOverlayLabel"] = ""
    else:
        kwargs["image"] = "pythonFamily.png"
        kwargs["imageOverlayLabel"] = "MB"

    cmds.shelfButton(**kwargs)
    print("[Maya Bridge] Shelf button added to '{}'".format(target_shelf))


# ── Show UI ──


def _show_ui():
    ui_path = os.path.join(_SCRIPT_DIR, "maya_bridge_ui.py")
    if not os.path.isfile(ui_path):
        print("[Maya Bridge] UI module not found at {}".format(ui_path))
        return
    import importlib.util
    import sys
    mod_name = "maya_bridge_ui"
    if mod_name in sys.modules:
        del sys.modules[mod_name]
    spec = importlib.util.spec_from_file_location(mod_name, ui_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    listener_mod = sys.modules.get("maya_bridge_listener")
    mod.show(listener_module=listener_mod, icon_path=ICON_PATH)


# ── Entry point ──


def _on_shelf_click():
    from PySide2.QtWidgets import QMessageBox

    panel_name = "mayaBridgePanel"
    ws_control = panel_name + "WorkspaceControl"
    
    # Check if panel exists
    panel_exists = False
    try:
        if cmds.workspaceControl(ws_control, exists=True):
            panel_exists = True
        elif cmds.workspaceControl(panel_name, exists=True):
            panel_exists = True
    except RuntimeError:
        panel_exists = False
    
    if panel_exists:
        reply = QMessageBox.question(
            None,
            "Maya Bridge",
            "Maya Bridge is already open. Would you like to restart it?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            try:
                cmds.workspaceControl(ws_control, edit=True, close=True)
            except RuntimeError:
                pass
            try:
                cmds.deleteUI(ws_control, control=True)
            except RuntimeError:
                pass
            if _active_port is not None:
                stop()
            _show_ui()
        return

    _show_ui()


_create_shelf_button()
maya.utils.executeDeferred(_on_shelf_click)
