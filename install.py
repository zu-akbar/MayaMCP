"""
Maya Bridge installer — sets up the skill and userSetup.py.
Run from the maya-bridge directory:
    python install.py
"""
import os
import shutil
import sys

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
BRIDGE_PATH = os.path.join(HERE, "maya_bridge.py").replace("\\", "/")
SKILL_SRC = os.path.join(HERE, "skill", "SKILL.md")

USERSETUP_SNIPPET = """
# Maya Bridge — open Python commandPort at startup
# See https://github.com/zu-akbar/maya-bridge
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
"""


def prompt(msg, options="y/n"):
    answer = input(f"{msg} [{options}]: ").strip().lower()
    return answer in ("y", "yes")


def prompt_choice(msg, choices):
    for i, c in enumerate(choices, 1):
        print(f"  {i}. {c}")
    while True:
        answer = input(f"{msg} [1-{len(choices)}]: ").strip()
        if answer.isdigit() and 1 <= int(answer) <= len(choices):
            return choices[int(answer) - 1]
        print("  Invalid choice, try again.")


def install_skill():
    print("\n-- Skill Installation --")
    if not prompt("Install the maya-bridge skill for your AI harness?"):
        return

    scope = prompt_choice("Install globally or per-project?", ["global", "project"])

    if scope == "global":
        dest = os.path.join(os.path.expanduser("~"), ".claude", "skills", "maya-bridge")
    else:
        dest = os.path.join(os.getcwd(), ".opencode", "skills", "maya-bridge")

    os.makedirs(dest, exist_ok=True)

    with open(SKILL_SRC) as f:
        content = f.read()
    content = content.replace("{{MAYA_BRIDGE_PATH}}", BRIDGE_PATH)

    dest_file = os.path.join(dest, "SKILL.md")
    with open(dest_file, "w") as f:
        f.write(content)
    print(f"  Written: {dest_file}")
    print(f"  Bridge path: {BRIDGE_PATH}")
    print("  Done.")


def patch_usersetup():
    print("\n-- userSetup.py --")
    print("  Maya Bridge requires a Python commandPort opened at Maya startup.")
    print("  This can be added to your userSetup.py automatically.")

    if not prompt("Patch userSetup.py?"):
        print("  Skipped. See README for the manual snippet.")
        return

    maya_version = input("  Maya version (e.g. 2023): ").strip() or "2023"
    if sys.platform == "win32":
        default = os.path.join(os.path.expanduser("~"), "Documents", "maya", maya_version, "scripts", "userSetup.py")
    else:
        default = os.path.join(os.path.expanduser("~"), "maya", maya_version, "scripts", "userSetup.py")

    path = input(f"  userSetup.py path [{default}]: ").strip() or default

    print("\n  The following will be appended to your userSetup.py:")
    print("  " + USERSETUP_SNIPPET.replace("\n", "\n  "))

    if not prompt("  Proceed?"):
        print("  Skipped.")
        return

    if os.path.exists(path):
        with open(path) as f:
            if "Maya Bridge" in f.read():
                print("  Already patched, skipping.")
                return

    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a") as f:
        f.write(USERSETUP_SNIPPET)
    print(f"  Written: {path}")
    print("  Done. Restart Maya for changes to take effect.")


if __name__ == "__main__":
    print("Maya Bridge Installer")
    print("==================")
    install_skill()
    patch_usersetup()
    print("\nAll done! See README.md for next steps.")
