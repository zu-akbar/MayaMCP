"""
Maya MCP installer — sets up the MCP server, skill, and userSetup.py.
Run from the MayaMCP directory:
    python install.py
"""
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SERVER_PATH = os.path.join(HERE, "maya_mcp_server.py").replace("\\", "/")
SKILL_SRC = os.path.join(HERE, "skill", "SKILL.md")

USERSETUP_SNIPPET = """
# Maya MCP — open Python commandPort at startup
# See https://github.com/zu-akbar/MayaMCP
import maya.cmds as cmds

def _mcp_open_port(port, source_type):
    port_str = ':{}'.format(port)
    try:
        if not cmds.commandPort(port_str, query=True):
            cmds.commandPort(name=port_str, sourceType=source_type, echoOutput=False)
        return True
    except RuntimeError:
        return False

def _mcp_open_port_auto(source_type, port_base=7001, port_max=7020):
    for port in range(port_base, port_max + 1):
        if _mcp_open_port(port, source_type):
            return port
    return None

_mcp_open_port_auto('python')
"""

MCP_CONFIG_OPENCODE = {
    "type": "local",
    "command": ["python", SERVER_PATH],
    "enabled": True
}

MCP_CONFIG_CLAUDECODE = {
    "mcpServers": {
        "maya": {
            "command": "python",
            "args": [SERVER_PATH]
        }
    }
}


def prompt(msg, options="y/n"):
    """Ask a y/n question, return True for yes."""
    answer = input(f"{msg} [{options}]: ").strip().lower()
    return answer in ("y", "yes")


def prompt_choice(msg, choices):
    """Ask user to pick from a numbered list, return chosen value."""
    for i, c in enumerate(choices, 1):
        print(f"  {i}. {c}")
    while True:
        answer = input(f"{msg} [1-{len(choices)}]: ").strip()
        if answer.isdigit() and 1 <= int(answer) <= len(choices):
            return choices[int(answer) - 1]
        print("  Invalid choice, try again.")


def install_mcp_server():
    print("\n── MCP Server Registration ──")
    if not prompt("Register the MCP server with your AI harness?"):
        return

    scope = prompt_choice("Install globally or per-project?", ["global", "project"])

    if scope == "global":
        config_path = os.path.join(os.path.expanduser("~"), ".config", "opencode", "opencode.json")
        os.makedirs(os.path.dirname(config_path), exist_ok=True)
        config = {}
        if os.path.exists(config_path):
            with open(config_path) as f:
                config = json.load(f)
        config.setdefault("mcp", {})["maya"] = MCP_CONFIG_OPENCODE
        with open(config_path, "w") as f:
            json.dump(config, f, indent=2)
        print(f"  Written: {config_path}")

    else:
        config_path = os.path.join(os.getcwd(), ".mcp.json")
        config = {}
        if os.path.exists(config_path):
            with open(config_path) as f:
                config = json.load(f)
        config.setdefault("mcpServers", {})["maya"] = MCP_CONFIG_CLAUDECODE["mcpServers"]["maya"]
        with open(config_path, "w") as f:
            json.dump(config, f, indent=2)
        print(f"  Written: {config_path}")

    print("  Done.")


def install_skill():
    print("\n── Skill Installation ──")
    if not prompt("Install the maya-mcp skill for your AI harness?"):
        return

    scope = prompt_choice("Install globally or per-project?", ["global", "project"])

    if scope == "global":
        dest = os.path.join(os.path.expanduser("~"), ".claude", "skills", "maya-mcp")
    else:
        dest = os.path.join(os.getcwd(), ".opencode", "skills", "maya-mcp")

    os.makedirs(dest, exist_ok=True)
    shutil.copy2(SKILL_SRC, os.path.join(dest, "SKILL.md"))
    print(f"  Written: {os.path.join(dest, 'SKILL.md')}")
    print("  Done.")


def patch_usersetup():
    print("\n── userSetup.py ──")
    print("  Maya MCP requires a Python commandPort opened at Maya startup.")
    print("  This can be added to your userSetup.py automatically.")

    if not prompt("Patch userSetup.py?"):
        print("  Skipped. See README for the manual snippet.")
        return

    # Find userSetup.py
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

    # Check if already patched
    if os.path.exists(path):
        with open(path) as f:
            if "Maya MCP" in f.read():
                print("  Already patched, skipping.")
                return

    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a") as f:
        f.write(USERSETUP_SNIPPET)
    print(f"  Written: {path}")
    print("  Done. Restart Maya for changes to take effect.")


if __name__ == "__main__":
    print("Maya MCP Installer")
    print("==================")
    install_mcp_server()
    install_skill()
    patch_usersetup()
    print("\nAll done! See README.md for next steps.")
