"""
Maya MCP Listener UI — shows session info and connected AI clients.
"""
import json
import os
import tempfile
import time

from PySide2.QtCore import Qt, QTimer
from PySide2.QtGui import QColor, QFont
from PySide2.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

CLIENT_DIR = os.path.join(tempfile.gettempdir(), "maya_mcp_clients")
STALE_THRESHOLD_SECONDS = 120


def _pid_alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


class McpListenerDialog(QDialog):
    _instance = None

    def __init__(self, port, parent=None):
        super().__init__(parent)
        self.port = port
        self.setWindowTitle("Maya MCP Listener")
        self.setMinimumWidth(420)
        self.setMinimumHeight(280)
        self.setWindowFlags(self.windowFlags() | Qt.Tool)
        self._build_ui()
        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self._refresh_clients)
        self._refresh_timer.start(3000)
        self._refresh_clients()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # Session info
        info_widget = QWidget()
        info_layout = QVBoxLayout(info_widget)
        info_layout.setContentsMargins(0, 0, 0, 0)
        info_layout.setSpacing(4)

        title = QLabel("Session Active")
        title.setFont(QFont("", 12, QFont.Bold))
        info_layout.addWidget(title)

        self._status_dot = QLabel()
        self._session_label = QLabel()
        self._session_label.setTextInteractionFlags(Qt.TextSelectableByMouse)

        status_row = QHBoxLayout()
        status_row.addWidget(self._status_dot)
        status_row.addWidget(self._session_label, 1)
        info_layout.addLayout(status_row)

        import maya.cmds as cmds
        scene = cmds.file(q=True, sceneName=True) or "(unsaved)"
        scene_short = os.path.basename(scene) if scene != "(unsaved)" else scene
        maya_ver = cmds.about(version=True)

        self._status_dot.setText("●")
        self._status_dot.setStyleSheet("color: #4CAF50; font-size: 16px;")
        self._session_label.setText(
            "Port: {}  |  Maya {}  |  {}".format(self.port, maya_ver, scene_short)
        )

        layout.addWidget(info_widget)

        # Connected clients section
        clients_label = QLabel("Connected AI Clients")
        clients_label.setFont(QFont("", 10, QFont.Bold))
        layout.addWidget(clients_label)

        self._client_tree = QTreeWidget()
        self._client_tree.setHeaderLabels(["Client", "Last Seen", "PID"])
        self._client_tree.setColumnWidth(0, 200)
        self._client_tree.setColumnWidth(1, 120)
        self._client_tree.setRootIsDecorated(False)
        self._client_tree.setAlternatingRowColors(True)
        layout.addWidget(self._client_tree)

        self._no_clients_label = QLabel("No AI clients connected yet.\nStart a Claude Code or OpenCode session with the MCP server configured.")
        self._no_clients_label.setAlignment(Qt.AlignCenter)
        self._no_clients_label.setStyleSheet("color: #888; padding: 20px;")
        layout.addWidget(self._no_clients_label)

    def _refresh_clients(self):
        import maya.cmds as cmds
        scene = cmds.file(q=True, sceneName=True) or "(unsaved)"
        scene_short = os.path.basename(scene) if scene != "(unsaved)" else scene
        maya_ver = cmds.about(version=True)
        self._session_label.setText(
            "Port: {}  |  Maya {}  |  {}".format(self.port, maya_ver, scene_short)
        )

        clients = self._discover_clients()
        self._client_tree.clear()

        if clients:
            self._client_tree.setVisible(True)
            self._no_clients_label.setVisible(False)
            for c in clients:
                item = QTreeWidgetItem([
                    c.get("client_name", "unknown"),
                    c.get("last_seen", ""),
                    str(c.get("pid", "")),
                ])
                age = c.get("_age_seconds", 999)
                if age > STALE_THRESHOLD_SECONDS:
                    item.setForeground(0, QColor("#888"))
                    item.setForeground(1, QColor("#888"))
                    item.setText(1, c.get("last_seen", "") + " (stale)")
                self._client_tree.addTopLevelItem(item)
        else:
            self._client_tree.setVisible(False)
            self._no_clients_label.setVisible(True)

    def _discover_clients(self):
        clients = []
        if not os.path.isdir(CLIENT_DIR):
            return clients
        prefix = "{}_".format(self.port)
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

    def closeEvent(self, event):
        McpListenerDialog._instance = None
        super().closeEvent(event)


def show(port, parent=None):
    if McpListenerDialog._instance is not None:
        McpListenerDialog._instance.close()
        McpListenerDialog._instance = None
    dialog = McpListenerDialog(port, parent=parent)
    McpListenerDialog._instance = dialog
    dialog.show()
    return dialog
