"""
Maya MCP Listener UI — dockable panel showing session info and connected AI clients.
"""
import json
import os
import tempfile
import time

from PySide2.QtCore import Qt, QTimer
from PySide2.QtGui import QColor, QFont
from PySide2.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

import maya.cmds as cmds
from maya.app.general.mayaMixin import MayaQWidgetDockableMixin

CLIENT_DIR = os.path.join(tempfile.gettempdir(), "maya_mcp_clients")
STALE_THRESHOLD_SECONDS = 120
WORKSPACE_NAME = "mcpListenerPanel"


def _pid_alive(pid):
    import sys
    if sys.platform == "win32":
        import ctypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x100000, False, pid)
        if handle:
            kernel32.CloseHandle(handle)
            return True
        return False
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


class McpListenerWidget(MayaQWidgetDockableMixin, QWidget):
    _instance = None

    def __init__(self, listener_module, parent=None):
        super().__init__(parent)
        self._listener = listener_module
        self.setObjectName(WORKSPACE_NAME)
        self._build_ui()
        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self._refresh)
        self._refresh_timer.start(3000)
        self._refresh()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(10, 10, 10, 10)

        header = QLabel("Maya MCP Listener")
        header.setFont(QFont("", 11, QFont.Bold))
        layout.addWidget(header)

        status_row = QHBoxLayout()
        self._status_dot = QLabel("●")
        self._status_dot.setFixedWidth(20)
        self._status_label = QLabel("Not connected")
        status_row.addWidget(self._status_dot)
        status_row.addWidget(self._status_label, 1)
        layout.addLayout(status_row)

        self._session_info = QLabel("")
        self._session_info.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._session_info.setWordWrap(True)
        layout.addWidget(self._session_info)

        self._toggle_btn = QPushButton("Connect")
        self._toggle_btn.setMinimumHeight(32)
        self._toggle_btn.clicked.connect(self._toggle_listener)
        layout.addWidget(self._toggle_btn)

        clients_label = QLabel("Connected AI Clients")
        clients_label.setFont(QFont("", 9, QFont.Bold))
        layout.addWidget(clients_label)

        self._client_tree = QTreeWidget()
        self._client_tree.setHeaderLabels(["Harness", "Client", "Last Seen"])
        self._client_tree.setColumnWidth(0, 100)
        self._client_tree.setColumnWidth(1, 140)
        self._client_tree.setRootIsDecorated(False)
        self._client_tree.setAlternatingRowColors(True)
        self._client_tree.setMaximumHeight(150)
        layout.addWidget(self._client_tree)

        self._no_clients_label = QLabel(
            "No AI clients connected yet.\n"
            "Use maya_connect in your AI harness."
        )
        self._no_clients_label.setAlignment(Qt.AlignCenter)
        self._no_clients_label.setStyleSheet("color: #888; padding: 12px;")
        layout.addWidget(self._no_clients_label)

        layout.addStretch()

    def _get_mod(self):
        import sys
        return sys.modules.get("maya_mcp_listener", self._listener)

    def _get_port(self):
        my_pid = os.getpid()
        session_dir = os.path.join(tempfile.gettempdir(), "maya_mcp_sessions")
        if not os.path.isdir(session_dir):
            return None
        for fname in os.listdir(session_dir):
            if not fname.endswith(".json"):
                continue
            try:
                with open(os.path.join(session_dir, fname)) as f:
                    data = json.load(f)
                if data.get("pid") == my_pid:
                    return data.get("port")
            except (json.JSONDecodeError, OSError):
                continue
        return None

    def _toggle_listener(self):
        mod = self._get_mod()
        if not mod:
            return
        if self._get_port() is not None:
            mod.stop()
        else:
            mod.start_listener()
        self._refresh()

    def _refresh(self):
        port = self._get_port()
        mod = self._get_mod()
        check_alive = getattr(mod, "_check_port_alive", None) if mod else None
        is_active = port is not None and check_alive and check_alive(port)

        if is_active:
            self._status_dot.setStyleSheet("color: #4CAF50; font-size: 16px;")
            self._status_label.setText("Listening on port {}".format(port))
            self._toggle_btn.setText("Disconnect")

            scene = cmds.file(q=True, sceneName=True) or "(unsaved)"
            scene_short = os.path.basename(scene) if scene != "(unsaved)" else scene
            maya_ver = cmds.about(version=True)
            self._session_info.setText(
                "Session ID: {}  |  Maya {}  |  {}".format(port, maya_ver, scene_short)
            )

            clients = self._discover_clients(port)
            self._client_tree.clear()
            if clients:
                self._client_tree.setVisible(True)
                self._no_clients_label.setVisible(False)
                for c in clients:
                    harness = c.get("harness", "") or "Unknown"
                    client = c.get("client_name", "unknown")
                    last_seen = c.get("last_seen", "")
                    item = QTreeWidgetItem([harness, client, last_seen])
                    age = c.get("_age_seconds", 999)
                    if age > STALE_THRESHOLD_SECONDS:
                        for col in range(3):
                            item.setForeground(col, QColor("#888"))
                        item.setText(2, last_seen + " (stale)")
                    self._client_tree.addTopLevelItem(item)
            else:
                self._client_tree.setVisible(False)
                self._no_clients_label.setVisible(True)
        else:
            self._status_dot.setStyleSheet("color: #F44336; font-size: 16px;")
            self._status_label.setText("Not connected")
            self._toggle_btn.setText("Connect")
            self._session_info.setText("")
            self._client_tree.clear()
            self._client_tree.setVisible(False)
            self._no_clients_label.setVisible(True)

    def _discover_clients(self, port):
        clients = []
        if not os.path.isdir(CLIENT_DIR):
            return clients
        prefix = "{}_".format(port)
        now = time.time()
        for fname in os.listdir(CLIENT_DIR):
            if not fname.startswith(prefix) or not fname.endswith(".json"):
                continue
            path = os.path.join(CLIENT_DIR, fname)
            try:
                with open(path) as f:
                    data = json.load(f)
                if not _pid_alive(data.get("pid", 0)):
                    os.remove(path)
                    continue
                try:
                    last = time.mktime(time.strptime(data["last_seen"], "%Y-%m-%dT%H:%M:%S"))
                    data["_age_seconds"] = now - last
                except (KeyError, ValueError):
                    data["_age_seconds"] = 0
                clients.append(data)
            except (json.JSONDecodeError, OSError):
                continue
        clients.sort(key=lambda c: c.get("_age_seconds", 0))
        return clients

    def dockCloseEventTriggered(self):
        McpListenerWidget._instance = None


def _delete_workspace():
    if cmds.workspaceControl(WORKSPACE_NAME, exists=True):
        cmds.workspaceControl(WORKSPACE_NAME, edit=True, close=True)
        cmds.deleteUI(WORKSPACE_NAME, control=True)


def show(listener_module, icon_path=""):
    """Open or focus the dockable MCP Listener panel."""
    if McpListenerWidget._instance is not None:
        McpListenerWidget._instance.raise_()
        return

    _delete_workspace()

    widget = McpListenerWidget(listener_module)
    widget.show(dockable=True, floating=False)
    ws_control = widget.objectName() + "WorkspaceControl"
    cmds.workspaceControl(
        ws_control,
        edit=True,
        label="MCP Listener",
        tabToControl=["AttributeEditor", -1],
        widthProperty="preferred",
        minimumWidth=280,
        restore=True,
    )
    widget.raise_()
    McpListenerWidget._instance = widget
