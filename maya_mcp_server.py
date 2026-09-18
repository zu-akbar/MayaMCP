"""
Maya MCP Server — connects any MCP-compatible AI harness to live Maya sessions.

Discovers Maya sessions via session files written by maya_mcp_listener.py,
sends raw Python code over TCP, and returns results.

Works with Claude Code, OpenCode, Cursor, or any MCP client via stdio.
No external dependencies — implements MCP JSON-RPC protocol directly.
"""
import json
import os
import platform
import socket
import sys
import tempfile
import time
import uuid

SERVER_NAME = "maya-mcp"
SERVER_VERSION = "0.1.0"
SESSION_DIR = os.path.join(tempfile.gettempdir(), "maya_mcp_sessions")
CLIENT_DIR = os.path.join(tempfile.gettempdir(), "maya_mcp_clients")
CLIENT_ID = str(uuid.uuid4())[:8]
CLIENT_NAME = "{}-{}".format(platform.node(), CLIENT_ID)
CLIENT_HARNESS = ""

_connected_sessions = []

# ── Maya session discovery and communication ──


def _pid_alive(pid):
    if sys.platform == "win32":
        import ctypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x100000, False, pid)  # SYNCHRONIZE
        if handle:
            kernel32.CloseHandle(handle)
            return True
        return False
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def _discover_sessions():
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


def _fire_and_forget(port, python_code):
    """Send Python code to Maya's commandPort and close immediately.

    Maya 2023 has a bug in CommandPort.py where returning results over the
    socket raises TypeError (bytes vs str). We avoid this by closing the
    socket right after sending — no response read. Results go through temp files.
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(5)
    try:
        s.connect(("127.0.0.1", port))
        s.sendall(python_code.encode("utf-8"))
        s.shutdown(socket.SHUT_WR)
    except Exception as e:
        return "[ERROR] {}".format(e)
    finally:
        s.close()
    return None


def _send_python(port, code, timeout=15.0):
    """Send Python to Maya via commandPort (sourceType=python), read result from temp file."""
    cmd_dir = os.path.join(tempfile.gettempdir(), "maya_mcp_cmds")
    os.makedirs(cmd_dir, exist_ok=True)

    cmd_id = "{}_{}".format(port, uuid.uuid4().hex[:8])
    cmd_file = os.path.join(cmd_dir, "{}.py".format(cmd_id)).replace("\\", "/")
    out_file = os.path.join(cmd_dir, "{}.out".format(cmd_id)).replace("\\", "/")

    with open(cmd_file, "w") as f:
        f.write(code)

    bootstrap = (
        "import sys as _s, io as _io, traceback as _tb\n"
        "_mcp_buf = _io.StringIO()\n"
        "_mcp_old = _s.stdout\n"
        "_s.stdout = _mcp_buf\n"
        "_mcp_err = None\n"
        "try:\n"
        "    exec(open('{cmd_file}').read())\n"
        "except Exception:\n"
        "    _mcp_err = _tb.format_exc()\n"
        "finally:\n"
        "    _s.stdout = _mcp_old\n"
        "_mcp_r = _mcp_err if _mcp_err else _mcp_buf.getvalue()\n"
        "with open('{out_file}', 'w') as _f:\n"
        "    _f.write(_mcp_r)\n"
    ).format(cmd_file=cmd_file, out_file=out_file)

    log = open(os.path.join(tempfile.gettempdir(), "maya_mcp_eval.log"), "w")
    log.write("port={} cmd_file={} out_file={}\n".format(port, cmd_file, out_file))
    log.write("bootstrap_len={}\n".format(len(bootstrap)))
    log.flush()

    err = _fire_and_forget(port, bootstrap)
    log.write("fire_and_forget result={}\n".format(repr(err)))
    log.flush()
    if err:
        log.close()
        return err

    # Wait for output file
    for _ in range(int(timeout * 4)):
        if os.path.exists(out_file):
            time.sleep(0.1)
            with open(out_file) as f:
                result = f.read()
            try:
                os.remove(cmd_file)
                os.remove(out_file)
            except OSError:
                pass
            return result.strip() if result.strip() else "(no output)"
        time.sleep(0.25)

    try:
        os.remove(cmd_file)
    except OSError:
        pass
    return "[ERROR] Timeout — Maya did not produce output"


def _resolve_port(session_id):
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


def _register_client(port):
    os.makedirs(CLIENT_DIR, exist_ok=True)
    path = os.path.join(CLIENT_DIR, "{}_{}.json".format(port, CLIENT_ID))
    data = {
        "client_id": CLIENT_ID,
        "client_name": CLIENT_NAME,
        "harness": CLIENT_HARNESS,
        "maya_port": port,
        "pid": os.getpid(),
        "last_seen": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def _unregister_client(port):
    path = os.path.join(CLIENT_DIR, "{}_{}.json".format(port, CLIENT_ID))
    try:
        os.remove(path)
    except OSError:
        pass


# ── Tool definitions ──

TOOLS = [
    {
        "name": "maya_list_sessions",
        "description": (
            "List all active Maya sessions. Shows port, scene, Maya version, "
            "PID, and whether each is connected to this chat session."
        ),
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "maya_connect",
        "description": (
            "Connect this chat session to a Maya session. "
            "Once connected, maya_eval can be called without specifying session_id. "
            "Multiple Maya sessions can be connected simultaneously."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    "description": "Maya session ID (port number from maya_list_sessions)",
                },
            },
            "required": ["session_id"],
        },
    },
    {
        "name": "maya_disconnect",
        "description": "Disconnect this chat session from a Maya session.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    "description": "Maya session ID to disconnect from",
                },
            },
            "required": ["session_id"],
        },
    },
    {
        "name": "maya_eval",
        "description": (
            "Execute Python code in a live Maya session. "
            "Code must be Python 3.9 compatible (Maya 2023). "
            "If only one Maya session is connected, session_id can be omitted. "
            "The return value is the string representation of the last expression. "
            "For complex results, use json.dumps() and print() in your code."
        ),
        "inputSchema": {
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
    },
    {
        "name": "maya_eval_file",
        "description": (
            "Execute a Python script file in a live Maya session. "
            "If only one Maya session is connected, session_id can be omitted."
        ),
        "inputSchema": {
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
    },
]


# ── Tool handlers ──


def handle_tool(name, arguments):
    if name == "maya_list_sessions":
        sessions = _discover_sessions()
        if not sessions:
            return "No active Maya sessions found. Run maya_mcp_listener.py in Maya first."
        return json.dumps(sessions, indent=2)

    if name == "maya_connect":
        port = _resolve_port(arguments["session_id"])
        if isinstance(port, str):
            return "[ERROR] " + port
        if port in _connected_sessions:
            return "Already connected to Maya session {}".format(port)
        _connected_sessions.append(port)
        _register_client(port)
        session_file = os.path.join(SESSION_DIR, "{}.json".format(port))
        try:
            with open(session_file) as f:
                info = json.load(f)
            scene = os.path.basename(info.get("scene", "")) or "(unsaved)"
            return "Connected to Maya session {} ({}, Maya {})".format(
                port, scene, info.get("maya_version", "?"))
        except (json.JSONDecodeError, OSError):
            return "Connected to Maya session {}".format(port)

    if name == "maya_disconnect":
        try:
            port = int(arguments["session_id"])
        except ValueError:
            return "[ERROR] Invalid session ID"
        if port not in _connected_sessions:
            return "[ERROR] Not connected to session {}".format(port)
        _connected_sessions.remove(port)
        _unregister_client(port)
        return "Disconnected from Maya session {}".format(port)

    if name == "maya_eval":
        port = _resolve_port(arguments.get("session_id"))
        if isinstance(port, str):
            return "[ERROR] " + port
        _register_client(port)
        result = _send_python(port, arguments["code"])
        return result if result else "(no output)"

    if name == "maya_eval_file":
        port = _resolve_port(arguments.get("session_id"))
        if isinstance(port, str):
            return "[ERROR] " + port
        file_path = arguments["file_path"]
        if not os.path.isfile(file_path):
            return "[ERROR] File not found: {}".format(file_path)
        _register_client(port)
        with open(file_path) as f:
            code = f.read()
        result = _send_python(port, code)
        return result if result else "(no output)"

    return "[ERROR] Unknown tool: {}".format(name)


# ── MCP JSON-RPC protocol over stdio ──


def _init_io():
    pass


def _write_response(response):
    line = json.dumps(response) + "\n"
    sys.stdout.buffer.write(line.encode("utf-8"))
    sys.stdout.buffer.flush()


def _read_request(_log=None):
    line = sys.stdin.buffer.readline()
    if _log:
        _log.write("  readline: {}\n".format(repr(line[:200])))
        _log.flush()
    if not line:
        return None
    line = line.decode("utf-8").strip()
    if not line:
        return None
    return json.loads(line)


def _handle_request(request):
    method = request.get("method", "")
    req_id = request.get("id")
    params = request.get("params", {})

    if method == "initialize":
        global CLIENT_HARNESS
        client_info = params.get("clientInfo", {})
        CLIENT_HARNESS = client_info.get("title", client_info.get("name", ""))
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": params.get("protocolVersion", "2024-11-05"),
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                "capabilities": {"tools": {"listChanged": False}},
            },
        }

    if method == "notifications/initialized":
        return None

    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {"tools": TOOLS},
        }

    if method == "tools/call":
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})
        result_text = handle_tool(tool_name, arguments)
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "content": [{"type": "text", "text": result_text}],
            },
        }

    if method == "ping":
        return {"jsonrpc": "2.0", "id": req_id, "result": {}}

    if req_id is not None:
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32601, "message": "Method not found: {}".format(method)},
        }
    return None


def main():
    _init_io()
    log = open(os.path.join(tempfile.gettempdir(), "maya_mcp_server.log"), "w")
    log.write("Server starting, platform={}, python={}\n".format(sys.platform, sys.version))
    log.write("stdin isatty={}, stdout isatty={}\n".format(sys.stdin.isatty(), sys.stdout.isatty()))
    log.write("stdin closed={}, readable={}\n".format(sys.stdin.closed, hasattr(sys.stdin, 'readable') and sys.stdin.readable()))
    log.flush()

    while True:
        try:
            log.write("Waiting for request...\n")
            log.flush()
            request = _read_request(_log=log)
            if request is None:
                log.write("Got None from _read_request, exiting\n")
                break
            log.write("REQ: {}\n".format(json.dumps(request)[:300]))
            log.flush()
            response = _handle_request(request)
            if response is not None:
                log.write("RES: {}\n".format(json.dumps(response)[:300]))
                log.flush()
                _write_response(response)
        except Exception:
            import traceback
            log.write("ERROR: {}\n".format(traceback.format_exc()))
            log.flush()
            break
    log.close()


if __name__ == "__main__":
    main()
