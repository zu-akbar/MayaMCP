"""
Maya Bridge — CLI tool that connects AI harnesses to live Maya sessions.

Discovers Maya sessions via session files written by maya_bridge_listener.py,
sends raw Python code over TCP, and returns results.

Usage:
    python maya_bridge.py list
    python maya_bridge.py connect <port> [--name "session name"]
    python maya_bridge.py disconnect <port>
    python maya_bridge.py eval --code "..." [--session PORT]
    python maya_bridge.py eval --file script.py [--session PORT]
"""
import argparse
import json
import os
import platform
import socket
import sys
import tempfile
import time
import uuid

SESSION_DIR = os.path.join(tempfile.gettempdir(), "maya_bridge_sessions")
CLIENT_DIR = os.path.join(tempfile.gettempdir(), "maya_bridge_clients")


# ── Client identity (persistent per machine) ──


def _get_client_id():
    os.makedirs(CLIENT_DIR, exist_ok=True)
    id_file = os.path.join(CLIENT_DIR, ".client_id")
    if os.path.exists(id_file):
        with open(id_file) as f:
            return f.read().strip()
    client_id = str(uuid.uuid4())[:8]
    with open(id_file, "w") as f:
        f.write(client_id)
    return client_id


def _detect_harness():
    if os.environ.get("CLAUDE_CODE"):
        return "Claude Code"
    if os.environ.get("CURSOR_SESSION_ID"):
        return "Cursor"
    if os.environ.get("OPENCODE"):
        return "OpenCode"
    return ""


CLIENT_ID = _get_client_id()
CLIENT_NAME = "{}-{}".format(platform.node(), CLIENT_ID)


# ── Connection state (file-based, survives process exit) ──


def _connections_file():
    return os.path.join(CLIENT_DIR, "connections_{}.json".format(CLIENT_ID))


def _load_connections():
    path = _connections_file()
    if not os.path.exists(path):
        return {}
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _save_connections(conns):
    os.makedirs(CLIENT_DIR, exist_ok=True)
    with open(_connections_file(), "w") as f:
        json.dump(conns, f, indent=2)


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
    conns = _load_connections()
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
            data["connected"] = str(data.get("port")) in conns
            sessions.append(data)
        except (json.JSONDecodeError, OSError):
            continue
    return sessions


def _fire_and_forget(port, python_code):
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
    cmd_dir = os.path.join(tempfile.gettempdir(), "maya_bridge_cmds")
    os.makedirs(cmd_dir, exist_ok=True)

    cmd_id = "{}_{}".format(port, uuid.uuid4().hex[:8])
    cmd_file = os.path.join(cmd_dir, "{}.py".format(cmd_id)).replace("\\", "/")
    out_file = os.path.join(cmd_dir, "{}.out".format(cmd_id)).replace("\\", "/")

    with open(cmd_file, "w") as f:
        f.write(code)

    bootstrap = (
        "import sys as _s, io as _io, traceback as _tb\n"
        "_mb_buf = _io.StringIO()\n"
        "_mb_old = _s.stdout\n"
        "_s.stdout = _mb_buf\n"
        "_mb_err = None\n"
        "try:\n"
        "    exec(open('{cmd_file}').read())\n"
        "except Exception:\n"
        "    _mb_err = _tb.format_exc()\n"
        "finally:\n"
        "    _s.stdout = _mb_old\n"
        "_mb_r = _mb_err if _mb_err else _mb_buf.getvalue()\n"
        "with open('{out_file}', 'w') as _f:\n"
        "    _f.write(_mb_r)\n"
    ).format(cmd_file=cmd_file, out_file=out_file)

    err = _fire_and_forget(port, bootstrap)
    if err:
        return err

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


def _resolve_port(conns, session_id=None):
    if session_id:
        try:
            port = int(session_id)
        except ValueError:
            return "Invalid session ID: {}".format(session_id)
        path = os.path.join(SESSION_DIR, "{}.json".format(port))
        if not os.path.exists(path):
            return "Session {} not found".format(session_id)
        return port

    live = [int(p) for p in conns if os.path.exists(
        os.path.join(SESSION_DIR, "{}.json".format(p))
    )]
    if len(live) == 1:
        return live[0]

    # Auto-resolve: if exactly one Maya session exists, use it without connect
    sessions = _discover_sessions()
    if len(sessions) == 1:
        return sessions[0]["port"]

    if len(live) == 0 and len(sessions) == 0:
        return "No Maya sessions found. Start maya_bridge_listener.py in Maya first."
    if len(live) == 0:
        return "No connected sessions. Use 'connect' first, or --session PORT."
    return "Multiple sessions connected ({}). Specify --session PORT.".format(
        ", ".join(str(p) for p in live)
    )


def _register_client(port, session_name=""):
    os.makedirs(CLIENT_DIR, exist_ok=True)
    path = os.path.join(CLIENT_DIR, "{}_{}.json".format(port, CLIENT_ID))
    data = {
        "client_id": CLIENT_ID,
        "client_name": CLIENT_NAME,
        "harness": _detect_harness(),
        "session_name": session_name,
        "maya_port": port,
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


# ── CLI subcommands ──


def cmd_list(args):
    sessions = _discover_sessions()
    if not sessions:
        print("No active Maya sessions found. Run maya_bridge_listener.py in Maya first.")
        return
    print(json.dumps(sessions, indent=2))


def cmd_connect(args):
    port = args.port
    path = os.path.join(SESSION_DIR, "{}.json".format(port))
    if not os.path.exists(path):
        print("[ERROR] Session {} not found".format(port))
        sys.exit(1)

    conns = _load_connections()
    if str(port) in conns:
        print("Already connected to Maya session {}".format(port))
        return

    session_name = args.name or ""
    conns[str(port)] = {"session_name": session_name, "connected_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    _save_connections(conns)
    _register_client(port, session_name)

    try:
        with open(path) as f:
            info = json.load(f)
        scene = os.path.basename(info.get("scene", "")) or "(unsaved)"
        print("Connected to Maya session {} ({}, Maya {})".format(
            port, scene, info.get("maya_version", "?")))
    except (json.JSONDecodeError, OSError):
        print("Connected to Maya session {}".format(port))


def cmd_disconnect(args):
    port = args.port
    conns = _load_connections()
    if str(port) not in conns:
        print("[ERROR] Not connected to session {}".format(port))
        sys.exit(1)
    del conns[str(port)]
    _save_connections(conns)
    _unregister_client(port)
    print("Disconnected from Maya session {}".format(port))


def cmd_eval(args):
    conns = _load_connections()

    if args.file:
        if not os.path.isfile(args.file):
            print("[ERROR] File not found: {}".format(args.file))
            sys.exit(1)
        with open(args.file) as f:
            code = f.read()
    elif args.code:
        code = args.code
    else:
        print("[ERROR] Provide --code or --file")
        sys.exit(1)

    port = _resolve_port(conns, args.session)
    if isinstance(port, str):
        print("[ERROR] " + port)
        sys.exit(1)

    session_name = conns.get(str(port), {}).get("session_name", "")
    _register_client(port, session_name)
    result = _send_python(port, code)
    print(result)


# ── Argument parser ──


def build_parser():
    parser = argparse.ArgumentParser(
        prog="maya_bridge",
        description="CLI bridge to live Maya sessions",
    )
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("list", help="List active Maya sessions")

    p_connect = sub.add_parser("connect", help="Connect to a Maya session")
    p_connect.add_argument("port", type=int, help="Maya session port")
    p_connect.add_argument("--name", default="", help="Name for this session")

    p_disconnect = sub.add_parser("disconnect", help="Disconnect from a Maya session")
    p_disconnect.add_argument("port", type=int, help="Maya session port")

    p_eval = sub.add_parser("eval", help="Execute Python in Maya")
    p_eval.add_argument("--code", help="Python code string")
    p_eval.add_argument("--file", help="Python script file path")
    p_eval.add_argument("--session", help="Target session port (optional if one session)")

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "list":
        cmd_list(args)
    elif args.command == "connect":
        cmd_connect(args)
    elif args.command == "disconnect":
        cmd_disconnect(args)
    elif args.command == "eval":
        cmd_eval(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
