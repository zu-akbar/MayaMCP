"""
Install the Maya Bridge shelf button in Maya without opening the UI.

Usage in Maya Script Editor (Python):
    exec(open("C:/Users/dkZuaAkb/Dev/Git/maya-bridge/install_shelf_button.py").read())
"""
import os
import maya.cmds as cmds
import maya.mel


def install():
    _SCRIPT_DIR = "C:/Users/dkZuaAkb/Dev/Git/maya-bridge"
    LISTENER_PATH = os.path.join(_SCRIPT_DIR, "maya_bridge_listener.py").replace("\\", "/")
    ICON_PATH = os.path.join(_SCRIPT_DIR, "maya-bridge-icon.jpg")
    BUTTON_NAME = "mayaBridge"

    target_shelf = "Custom"
    shelf_top = maya.mel.eval("$tmpVar=$gShelfTopLevel")
    if not cmds.shelfLayout(target_shelf, exists=True):
        target_shelf = cmds.tabLayout(shelf_top, query=True, selectTab=True)

    existing = cmds.shelfLayout(target_shelf, query=True, childArray=True) or []
    for child in existing:
        if cmds.shelfButton(child, query=True, exists=True):
            try:
                if cmds.shelfButton(child, query=True, label=True) == BUTTON_NAME:
                    cmds.deleteUI(child)
            except RuntimeError:
                pass

    click_cmd = (
        'import importlib.util, sys, maya.utils\n'
        'def _bridge_open():\n'
        '    if "maya_bridge_listener" in sys.modules: del sys.modules["maya_bridge_listener"]\n'
        '    spec = importlib.util.spec_from_file_location("maya_bridge_listener", "{path}")\n'
        '    mod = importlib.util.module_from_spec(spec)\n'
        '    sys.modules["maya_bridge_listener"] = mod\n'
        '    spec.loader.exec_module(mod)\n'
        'maya.utils.executeDeferred(_bridge_open)\n'
    ).format(path=LISTENER_PATH)

    kwargs = {
        "parent": target_shelf,
        "label": BUTTON_NAME,
        "annotation": "Maya Bridge - connect AI harness to Maya",
        "command": click_cmd,
        "sourceType": "python",
    }
    if os.path.isfile(ICON_PATH):
        kwargs["image"] = ICON_PATH
        kwargs["imageOverlayLabel"] = ""
    else:
        kwargs["image"] = "pythonFamily.png"
        kwargs["imageOverlayLabel"] = "MB"

    cmds.shelfButton(**kwargs)
    print("[Maya Bridge] Shelf button installed on '{}'".format(target_shelf))


install()
