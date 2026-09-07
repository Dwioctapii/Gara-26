"""Jembatan HiveMQ untuk fallback state dashboard."""

from __future__ import annotations

import json
import os
import socket
import threading
import time

try:
    import paho.mqtt.client as mqtt
except ImportError:
    mqtt = None

# Import dari server_common (bukan server.py)
from mod12_server_common import DEBUG_ACTIVE, _debug
from mod03_robot_topic import TOPIK_GUI_STATE, robot_topic
import mod01_config as config

TOPIK_STATE = "/sistem_broadcast/state_dan_variabel"

class MqttBridge:
    def __init__(self):
        self.state_terakhir = None
        self.state_interval = 0.2   # 5 Hz
        self.client = None
        self.connected = threading.Event()
        self.stop_event = threading.Event()

    def start(self) -> None:
        if mqtt is None:
            raise RuntimeError("paho-mqtt belum terpasang")
        if not config.MQTT_HOST or not config.MQTT_USER or not config.MQTT_PASS:
            raise RuntimeError("ASV_MQTT_HOST, ASV_MQTT_USER, dan ASV_MQTT_PASS wajib diisi")

        robot_topic.berlangganan(TOPIK_GUI_STATE, self._terima_state)
        robot_topic.mulai()

        client_id = f"asv-backend-{socket.gethostname()}-{os.getpid()}"
        self.client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=client_id,
            protocol=mqtt.MQTTv311,
        )
        self.client.username_pw_set(config.MQTT_USER, config.MQTT_PASS)
        self.client.tls_set()
        self.client.reconnect_delay_set(min_delay=1, max_delay=30)
        self.client.on_connect = self._on_connect
        self.client.on_connect_fail = self._on_connect_fail
        self.client.on_disconnect = self._on_disconnect
        if DEBUG_ACTIVE:
            self.client.on_log = self._on_log

        self.client.connect_async(config.MQTT_HOST, config.MQTT_PORT, keepalive=30)
        self.client.loop_start()

        threading.Thread(target=self._loop_broadcast, daemon=True, name="mqtt-state").start()
        _debug("MQTT", "starting", {
            "host": config.MQTT_HOST,
            "port": config.MQTT_PORT,
            "client_id": client_id,
        })

    def stop(self):
        self.stop_event.set()
        if self.client:
            self.client.disconnect()
            self.client.loop_stop()
        robot_topic.berhenti()

    def _terima_state(self, _topik, data):
        if isinstance(data, dict):
            self.state_terakhir = data

    # ---- Callbacks ----
    def _on_connect(self, _client, _userdata, _flags, reason_code, _properties):
        if reason_code != 0:
            _debug("MQTT", "connection_rejected", {"reason": str(reason_code)})
            return
        self.connected.set()
        _debug("MQTT", "connected", {"host": config.MQTT_HOST})

    def _on_connect_fail(self, _client, _userdata):
        self.connected.clear()
        _debug("MQTT", "connection_failed", {
            "host": config.MQTT_HOST,
            "port": config.MQTT_PORT,
        })

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

    def _publish_state(self):
        if self.state_terakhir:
            ringkasan = {
                "timestamp": self.state_terakhir.get("timestamp"),
                "missionState": self.state_terakhir.get("missionState"),
            }
            self._publish_json(
                TOPIK_STATE,
                self.state_terakhir,
                qos=0,
                debug_value=ringkasan,
            )

    # ---- Main loop ----
    def _loop_broadcast(self):
        next_state = 0.0
        while not self.stop_event.is_set():
            if not self.connected.wait(0.1):
                continue
            now = time.monotonic()

            # State broadcast (5 Hz)
            if now >= next_state:
                self._publish_state()
                next_state = now + self.state_interval

            time.sleep(0.01)


JembatanMqtt = MqttBridge


def main() -> None:
    jembatan = MqttBridge()
    jembatan.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        jembatan.stop()


if __name__ == "__main__":
    main()
