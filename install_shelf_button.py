"""
Install the MCP Listener shelf button in Maya without opening the UI.

Usage in Maya Script Editor (Python):
    exec(open("C:/Users/dkZuaAkb/Dev/Git/MayaMCP/install_shelf_button.py").read())
"""
import os
import maya.cmds as cmds
import maya.mel

_SCRIPT_DIR = "C:/Users/dkZuaAkb/Dev/Git/MayaMCP"
LISTENER_PATH = os.path.join(_SCRIPT_DIR, "maya_mcp_listener.py").replace("\\", "/")
ICON_PATH = os.path.join(_SCRIPT_DIR, "maya-mcp-icon.jpg")
SHELF_BUTTON_NAME = "mcpListener"


def install():
    target_shelf = "Custom"
    shelf_top = maya.mel.eval("$tmpVar=$gShelfTopLevel")
    if not cmds.shelfLayout(target_shelf, exists=True):
        target_shelf = cmds.tabLayout(shelf_top, query=True, selectTab=True)

    existing = cmds.shelfLayout(target_shelf, query=True, childArray=True) or []
    for child in existing:
        if cmds.shelfButton(child, query=True, exists=True):
            try:
                if cmds.shelfButton(child, query=True, label=True) == SHELF_BUTTON_NAME:
                    cmds.deleteUI(child)
            except RuntimeError:
                pass

    click_cmd = 'exec(open("{}").read())'.format(LISTENER_PATH)

    kwargs = {
        "parent": target_shelf,
        "label": SHELF_BUTTON_NAME,
        "annotation": "MCP Listener - connect AI harness to Maya",
        "command": click_cmd,
        "sourceType": "python",
    }
    if os.path.isfile(ICON_PATH):
        kwargs["image"] = ICON_PATH
        kwargs["imageOverlayLabel"] = ""
    else:
        kwargs["image"] = "pythonFamily.png"
        kwargs["imageOverlayLabel"] = "MCP"

    cmds.shelfButton(**kwargs)
    print("[MCP] Shelf button installed on '{}'. Click it to open the MCP Listener panel.".format(target_shelf))


install()
