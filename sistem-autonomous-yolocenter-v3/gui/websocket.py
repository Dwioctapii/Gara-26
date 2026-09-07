"""Backend pub/sub untuk seluruh jendela GUI lama."""

from __future__ import annotations

import base64
import queue
import threading
import uuid

from mod03_robot_topic import TOPIK_FRAME, TOPIK_GUI_STATE, TOPIK_PERINTAH, RobotTopicClient


class GUIWebSocket:
    """Menjaga antarmuka lama GUI, dengan backend RobotTopic baru."""

    def __init__(self, component, camera=False):
        self.component = component
        self.camera_enabled = camera
        self.state = {}
        self.frame = None
        self.status = "CONNECTING"
        self.version = 0
        self.frame_version = 0
        self.lock = threading.Lock()
        self.commands = queue.Queue()
        self.stop_event = threading.Event()
        self.topik = RobotTopicClient()

    def start(self):
        self.topik.berlangganan(TOPIK_GUI_STATE, self._terima_state)
        if self.camera_enabled:
            self.topik.berlangganan(TOPIK_FRAME, self._terima_frame)
        self.topik.mulai()
        threading.Thread(target=self._kirim_perintah, daemon=True, name="gui-command").start()

    def stop(self):
        self.stop_event.set()
        self.topik.berhenti()

    def command(self, name, **data):
        self.commands.put({"id": uuid.uuid4().hex[:8], "command": name, **data})

    def snapshot(self):
        with self.lock:
            status = "CONNECTED" if self.topik.sinyal_terhubung.is_set() else "RECONNECT"
            return self.state, self.frame, status, self.version, self.frame_version

    def _terima_state(self, _topik, data):
        if not isinstance(data, dict):
            return
        with self.lock:
            self.state = data
            self.version += 1

    def _terima_frame(self, _topik, data):
        if not isinstance(data, dict) or not isinstance(data.get("jpeg"), str):
            return
        try:
            frame = base64.b64decode(data["jpeg"], validate=True)
        except ValueError:
            return
        with self.lock:
            self.frame = frame
            self.frame_version += 1

    def _kirim_perintah(self):
        while not self.stop_event.is_set():
            try:
                perintah = self.commands.get(timeout=0.1)
            except queue.Empty:
                continue
            self.topik.publikasi(TOPIK_PERINTAH, perintah, dipertahankan=False)
