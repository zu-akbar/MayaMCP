"""
Maya MCP Server — connects any MCP-compatible AI harness to live Maya sessions.

Discovers Maya sessions via session files written by maya_mcp_listener.py,
sends raw Python code over TCP, and returns results.

Works with Claude Code, OpenCode, Cursor, or any MCP client via stdio.
"""
import asyncio
import json
import os
import platform
import socket
import tempfile
import time
import uuid

import mcp.server.stdio
from mcp.server.lowlevel import Server
from mcp.server.models import InitializationOptions
from mcp.types import Tool, TextContent

SERVER_NAME = "maya-mcp"
SESSION_DIR = os.path.join(tempfile.gettempdir(), "maya_mcp_sessions")
CLIENT_DIR = os.path.join(tempfile.gettempdir(), "maya_mcp_clients")
CLIENT_ID = str(uuid.uuid4())[:8]
CLIENT_NAME = "{}-{}".format(platform.node(), CLIENT_ID)

_connected_sessions: list[int] = []


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def _discover_sessions() -> list[dict]:
    sessions = []
    if not os.path.isdir(SESSION_DIR):
        return sessions
    for fname in os.listdir(SESSION_DIR):
        if not fname.endswith(".json"):
            continue
        path = os.path.join(SESSION_DIR, fname)
        try:
            with open(path) as f:
                data = json.load(f)
            if not _pid_alive(data.get("pid", 0)):
                os.remove(path)
                continue
            data["connected"] = data.get("port") in _connected_sessions
            sessions.append(data)
        except (json.JSONDecodeError, OSError):
            continue
    return sessions


def _send_python(port: int, code: str, timeout: float = 10.0) -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect(("127.0.0.1", port))
        s.sendall(code.encode("utf-8"))
        s.shutdown(socket.SHUT_WR)
        result = b""
        while True:
            chunk = s.recv(8192)
            if not chunk:
                break
            result += chunk
        return result.decode("utf-8").strip().replace(chr(0), "")
    except socket.timeout:
        return "[ERROR] Timeout waiting for Maya response"
    except ConnectionRefusedError:
        return "[ERROR] Connection refused — Maya session may be closed"
    except Exception as e:
        return "[ERROR] {}".format(e)
    finally:
        s.close()


def _resolve_port(session_id: str | None) -> int | str:
    if session_id:
        try:
            port = int(session_id)
        except ValueError:
            return "Invalid session ID: {}".format(session_id)
        path = os.path.join(SESSION_DIR, "{}.json".format(port))
        if not os.path.exists(path):
            return "Session {} not found".format(session_id)
        return port

    live = [p for p in _connected_sessions if os.path.exists(
        os.path.join(SESSION_DIR, "{}.json".format(p))
    )]
    if len(live) == 1:
        return live[0]
    if len(live) == 0:
        return "No connected sessions. Use maya_connect first."
    return "Multiple sessions connected ({}). Specify session_id.".format(
        ", ".join(str(p) for p in live)
    )


def _register_client(port: int):
    os.makedirs(CLIENT_DIR, exist_ok=True)
    path = os.path.join(CLIENT_DIR, "{}_{}.json".format(port, CLIENT_ID))
    data = {
        "client_id": CLIENT_ID,
        "client_name": CLIENT_NAME,
        "maya_port": port,
        "pid": os.getpid(),
        "last_seen": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def _unregister_client(port: int):
    path = os.path.join(CLIENT_DIR, "{}_{}.json".format(port, CLIENT_ID))
    try:
        os.remove(path)
    except OSError:
        pass


TOOLS = [
    Tool(
        name="maya_list_sessions",
        description=(
            "List all active Maya sessions. Shows port, scene, Maya version, "
            "PID, and whether each is connected to this chat session."
        ),
        inputSchema={"type": "object", "properties": {}, "required": []},
    ),
    Tool(
        name="maya_connect",
        description=(
            "Connect this chat session to a Maya session. "
            "Once connected, maya_eval can be called without specifying session_id. "
            "Multiple Maya sessions can be connected simultaneously."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    "description": "Maya session ID (port number from maya_list_sessions)",
                },
            },
            "required": ["session_id"],
        },
    ),
    Tool(
        name="maya_disconnect",
        description="Disconnect this chat session from a Maya session.",
        inputSchema={
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    "description": "Maya session ID to disconnect from",
                },
            },
            "required": ["session_id"],
        },
    ),
    Tool(
        name="maya_eval",
        description=(
            "Execute Python code in a live Maya session. "
            "Code must be Python 3.9 compatible (Maya 2023). "
            "If only one Maya session is connected, session_id can be omitted. "
            "The return value is the string representation of the last expression. "
            "For complex results, use json.dumps() and print() in your code."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    "description": "Maya session ID (optional if only one session is connected)",
                },
                "code": {
                    "type": "string",
                    "description": "Python code to execute in Maya",
                },
            },
            "required": ["code"],
        },
    ),
    Tool(
        name="maya_eval_file",
        description=(
            "Execute a Python script file in a live Maya session. "
            "If only one Maya session is connected, session_id can be omitted."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    "description": "Maya session ID (optional if only one session is connected)",
                },
                "file_path": {
                    "type": "string",
                    "description": "Path to the Python script file to execute in Maya",
                },
            },
            "required": ["file_path"],
        },
    ),
]

server = Server(SERVER_NAME)


@server.list_tools()
async def list_tools() -> list[Tool]:
    return TOOLS


def _error(msg: str) -> list[TextContent]:
    return [TextContent(type="text", text="[ERROR] {}".format(msg))]


def _text(msg: str) -> list[TextContent]:
    return [TextContent(type="text", text=msg)]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name == "maya_list_sessions":
        sessions = _discover_sessions()
        if not sessions:
            return _text("No active Maya sessions found. Run maya_mcp_listener.py in Maya first.")
        return _text(json.dumps(sessions, indent=2))

    if name == "maya_connect":
        port = _resolve_port(arguments["session_id"])
        if isinstance(port, str):
            return _error(port)
        if port in _connected_sessions:
            return _text("Already connected to Maya session {} ".format(port))
        _connected_sessions.append(port)
        _register_client(port)
        session_file = os.path.join(SESSION_DIR, "{}.json".format(port))
        try:
            with open(session_file) as f:
                info = json.load(f)
            scene = os.path.basename(info.get("scene", "")) or "(unsaved)"
            return _text("Connected to Maya session {} ({}, Maya {})".format(
                port, scene, info.get("maya_version", "?")))
        except (json.JSONDecodeError, OSError):
            return _text("Connected to Maya session {}".format(port))

    if name == "maya_disconnect":
        try:
            port = int(arguments["session_id"])
        except ValueError:
            return _error("Invalid session ID")
        if port not in _connected_sessions:
            return _error("Not connected to session {}".format(port))
        _connected_sessions.remove(port)
        _unregister_client(port)
        return _text("Disconnected from Maya session {}".format(port))

    if name == "maya_eval":
        port = _resolve_port(arguments.get("session_id"))
        if isinstance(port, str):
            return _error(port)
        _register_client(port)
        result = _send_python(port, arguments["code"])
        return _text(result if result else "(no output)")

    if name == "maya_eval_file":
        port = _resolve_port(arguments.get("session_id"))
        if isinstance(port, str):
            return _error(port)
        file_path = arguments["file_path"]
        if not os.path.isfile(file_path):
            return _error("File not found: {}".format(file_path))
        _register_client(port)
        with open(file_path) as f:
            code = f.read()
        result = _send_python(port, code)
        return _text(result if result else "(no output)")

    return _error("Unknown tool: {}".format(name))


async def run():
    async with mcp.server.stdio.stdio_server() as (read, write):
        await server.run(
            read, write,
            InitializationOptions(
                server_name=SERVER_NAME,
                server_version="0.1.0",
                capabilities=server.get_capabilities(
                    notification_options=None,
                    experimental_capabilities={},
                ),
            ),
        )


if __name__ == "__main__":
    asyncio.run(run())
