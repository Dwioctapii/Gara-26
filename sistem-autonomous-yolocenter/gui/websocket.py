"""Satu koneksi WebSocket untuk seluruh GUI."""

import asyncio
import json
import os
import queue
import threading
import uuid
from pathlib import Path

import websockets


def _urls():
    custom = os.getenv("ASV_GUI_WS_URLS")
    if custom:
        return [url.strip() for url in custom.split(",") if url.strip()]
    config = Path(__file__).resolve().parents[2] / "config.txt"
    values = {}
    if config.exists():
        for line in config.read_text(encoding="utf-8").splitlines():
            if "=" in line:
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip()
    port = values.get("local_ws_port", os.getenv("ASV_WS_PORT", "8765"))
    ip = values.get("local_ip_robot", "127.0.0.1")
    return list(dict.fromkeys([f"ws://127.0.0.1:{port}", f"ws://{ip}:{port}"]))


class GUIWebSocket:
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

    def start(self):
        threading.Thread(target=lambda: asyncio.run(self._run()), daemon=True).start()

    def stop(self):
        self.stop_event.set()

    def command(self, name, **data):
        self.commands.put({"id": uuid.uuid4().hex[:8], "command": name, **data})

    def snapshot(self):
        with self.lock:
            return self.state, self.frame, self.status, self.version, self.frame_version

    async def _run(self):
        urls = _urls()
        index = 0
        while not self.stop_event.is_set():
            url = urls[index % len(urls)]
            index += 1
            try:
                self.status = f"CONNECTING {url}"
                async with websockets.connect(url, open_timeout=2, max_size=4_000_000) as ws:
                    self.status = f"CONNECTED {url}"
                    await ws.send(json.dumps({
                        "type": "subscribe", "component": self.component,
                        "state": True, "camera": self.camera_enabled,
                        "state_hz": 10, "camera_hz": 15, "jpeg_quality": 75,
                    }))
                    await self._session(ws)
            except Exception as error:
                self.status = f"RECONNECT {type(error).__name__}"
                await asyncio.sleep(1)

    async def _session(self, ws):
        async def receive():
            async for raw in ws:
                with self.lock:
                    if isinstance(raw, bytes):
                        self.frame = raw
                        self.frame_version += 1
                    else:
                        value = json.loads(raw)
                        if value.get("type") not in {"ack", "subscribed"}:
                            self.state = value
                            self.version += 1

        async def send():
            while not self.stop_event.is_set():
                try:
                    command = self.commands.get_nowait()
                except queue.Empty:
                    await asyncio.sleep(0.02)
                    continue
                await ws.send(json.dumps(command))

        tasks = [asyncio.create_task(receive()), asyncio.create_task(send())]
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
