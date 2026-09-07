"""Jembatan HiveMQ: broadcast foto + state, tanpa ketergantungan config.txt."""

from __future__ import annotations

import json
import socket
import threading
import time
import os
from pathlib import Path

try:
    import paho.mqtt.client as mqtt
except ImportError:
    mqtt = None

# Import dari server_common (bukan server.py)
from server_common import DEBUG_ACTIVE, PHOTO_CHECK_SECONDS, _debug, _prepare_photo_transfer

TOPIK_FOTO  = "/sistem_broadcast/foto"
TOPIK_STATE = "/sistem_broadcast/state_dan_variabel"

# Kredensial hardcode (sama dengan client)
MQTT_HOST = "b786a44b5790491898b3c676180e7862.s1.eu.hivemq.cloud"
MQTT_PORT = 8883
MQTT_USER = "noxindocraft"
MQTT_PASS = "Zancraft1&"


class JembatanMqtt:
    def __init__(self, photo_dir, store):
        self.photo_dir = Path(photo_dir)
        self.store = store
        self.photo_interval = max(
            PHOTO_CHECK_SECONDS,
            float(os.getenv("ASV_MQTT_PHOTO_BROADCAST_SECONDS", "5")),
        )
        self.state_interval = 0.2   # 5 Hz
        self.client = None
        self.connected = threading.Event()
        self.stop_event = threading.Event()

    def start(self) -> None:
        if mqtt is None:
            print("[MQTT] paho-mqtt belum terpasang; jalankan pip install paho-mqtt")
            return

        client_id = f"asv-backend-{socket.gethostname()}-{os.getpid()}"
        self.client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=client_id,
            protocol=mqtt.MQTTv311,
        )
        self.client.username_pw_set(MQTT_USER, MQTT_PASS)
        self.client.tls_set()
        self.client.reconnect_delay_set(min_delay=1, max_delay=30)
        self.client.on_connect = self._on_connect
        self.client.on_connect_fail = self._on_connect_fail
        self.client.on_disconnect = self._on_disconnect
        if DEBUG_ACTIVE:
            self.client.on_log = self._on_log

        self.client.connect_async(MQTT_HOST, MQTT_PORT, keepalive=30)
        self.client.loop_start()

        # Thread untuk broadcast state + foto
        threading.Thread(target=self._loop_broadcast, daemon=True, name="mqtt-broadcast").start()
        _debug("MQTT", "starting", {"host": MQTT_HOST, "port": MQTT_PORT, "client_id": client_id})

    def stop(self):
        self.stop_event.set()
        if self.client:
            self.client.disconnect()
            self.client.loop_stop()

    # ---- Callbacks ----
    def _on_connect(self, _client, _userdata, _flags, reason_code, _properties):
        if reason_code != 0:
            _debug("MQTT", "connection_rejected", {"reason": str(reason_code)})
            return
        self.connected.set()
        _debug("MQTT", "connected", {"host": MQTT_HOST})

    def _on_connect_fail(self, _client, _userdata):
        self.connected.clear()
        _debug("MQTT", "connection_failed", {"host": MQTT_HOST, "port": MQTT_PORT})

    def _on_disconnect(self, _client, _userdata, _flags, reason_code, _properties):
        self.connected.clear()
        _debug("MQTT", "disconnected", {"reason": str(reason_code)})

    def _on_log(self, _client, _userdata, level, message):
        _debug("MQTT-LIB", "log", {"level": level, "message": message})

    # ---- Publish helpers ----
    def _publish_json(self, topic, value, qos=0, retain=False, debug_value=None):
        if not self.client or not self.connected.is_set():
            return
        payload = json.dumps(value, separators=(",", ":"), ensure_ascii=False)
        info = self.client.publish(topic, payload, qos=qos, retain=retain)
        _debug("MQTT-PUB", "published", {
            "topic": topic,
            "mid": info.mid,
            "bytes": len(payload.encode()),
            "data": value if debug_value is None else debug_value,
        })

    def _publish_photo(self, camera: str):
        path = self.photo_dir / f"{camera}.jpg"
        prepared = _prepare_photo_transfer(camera, path, None)
        if not prepared:
            return
        metadata, chunks, _ = prepared
        tid = metadata["transfer_id"]
        self._publish_json(TOPIK_FOTO, {"type": "photo_start", **metadata})
        for idx, chunk in enumerate(chunks):
            msg = {
                "type": "photo_chunk",
                "camera": camera,
                "transfer_id": tid,
                "index": idx,
                "total_chunks": len(chunks),
                "data": chunk,
            }
            self._publish_json(TOPIK_FOTO, msg, debug_value={k:v for k,v in msg.items() if k!="data"})
        self._publish_json(TOPIK_FOTO, {
            "type": "photo_end",
            "camera": camera,
            "transfer_id": tid,
            "sha256": metadata["sha256"],
        })

    def _publish_state(self):
        snap = self.store.snapshot()
        # Kirim hanya field penting (bukan data biner)
        state_payload = {
            "timestamp": snap.get("timestamp"),
            "mode": snap.get("mode"),
            "arm": snap.get("arm"),
            "missionState": snap.get("missionState"),
            "currentTrack": snap.get("currentTrack"),
            "mission": snap.get("mission", {}),
            "gps": {k: snap["gps"].get(k) for k in ("lat","lon","sog","cog","satellites","fix")},
            "position": snap.get("position"),
            "orientation": snap.get("orientation"),
            "battery1": snap.get("battery1"),
            "sensors": snap.get("sensors"),
            "detection": snap.get("detection"),
        }
        self._publish_json(TOPIK_STATE, state_payload, qos=0)

    # ---- Main loop ----
    def _loop_broadcast(self):
        next_photo = 0.0
        next_state = 0.0
        while not self.stop_event.is_set():
            if not self.connected.wait(0.1):
                continue
            now = time.monotonic()

            # State broadcast (5 Hz)
            if now >= next_state:
                self._publish_state()
                next_state = now + self.state_interval

            # Foto broadcast
            if now >= next_photo:
                for cam in ("atas", "bawah"):
                    if (self.photo_dir / f"{cam}.jpg").is_file():
                        self._publish_photo(cam)
                next_photo = now + self.photo_interval

            time.sleep(0.01)