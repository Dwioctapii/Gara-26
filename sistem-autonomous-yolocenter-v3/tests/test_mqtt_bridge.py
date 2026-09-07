import importlib.util
import json
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch


class MqttBridgeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        modul_paho = types.ModuleType("paho")
        modul_paho.__path__ = []
        modul_mqtt = types.ModuleType("paho.mqtt")
        modul_mqtt.__path__ = []
        modul_client = types.ModuleType("paho.mqtt.client")
        modul_client.CallbackAPIVersion = types.SimpleNamespace(VERSION2=2)
        modul_client.MQTTv311 = 4
        modul_paho.mqtt = modul_mqtt
        modul_mqtt.client = modul_client

        class RobotTopicPalsu:
            def berlangganan(self, topik, penangan):
                self.langganan = (topik, penangan)

            def mulai(self):
                self.dimulai = True

            def berhenti(self):
                self.dihentikan = True

        modul_topik = types.ModuleType("mod03_robot_topic")
        modul_topik.TOPIK_GUI_STATE = "/local_scope/gui/state"
        modul_topik.robot_topic = RobotTopicPalsu()

        root = Path(__file__).resolve().parents[1]
        spesifikasi = importlib.util.spec_from_file_location(
            "mod10_mqtt_untuk_tes",
            root / "mod10_broadcast_mqtt_worker.py",
        )
        cls.modul = importlib.util.module_from_spec(spesifikasi)
        with patch.dict(
            sys.modules,
            {
                "paho": modul_paho,
                "paho.mqtt": modul_mqtt,
                "paho.mqtt.client": modul_client,
                "mod03_robot_topic": modul_topik,
            },
        ):
            spesifikasi.loader.exec_module(cls.modul)

    def test_start_membuat_client_paho_dan_koneksi_tls(self):
        class ClientPalsu:
            def username_pw_set(self, pengguna, sandi):
                self.login = (pengguna, sandi)

            def tls_set(self):
                self.tls = True

            def reconnect_delay_set(self, min_delay, max_delay):
                self.jeda = (min_delay, max_delay)

            def connect_async(self, host, port, keepalive):
                self.koneksi = (host, port, keepalive)

            def loop_start(self):
                self.loop_dimulai = True

        client = ClientPalsu()
        pembuat_client = unittest.mock.Mock(return_value=client)
        self.modul.mqtt.Client = pembuat_client
        jembatan = self.modul.MqttBridge()

        with patch.multiple(
            self.modul.config,
            MQTT_HOST="broker.example.test",
            MQTT_PORT=8883,
            MQTT_USER="pengguna-tes",
            MQTT_PASS="sandi-tes",
        ):
            with patch.object(self.modul.threading, "Thread") as pembuat_utas:
                with patch.object(self.modul, "_debug"):
                    jembatan.start()

            argumen = pembuat_client.call_args
            self.assertIn("asv-backend-", argumen.kwargs["client_id"])
            self.assertEqual(client.koneksi, ("broker.example.test", 8883, 30))
        self.assertTrue(client.tls)
        self.assertTrue(client.loop_dimulai)
        pembuat_utas.assert_called_once()

    def test_state_dipublikasikan_utuh_ke_cloud_dengan_qos_nol(self):
        class HasilPublikasi:
            mid = 7

        class ClientPalsu:
            def publish(self, topik, payload, qos, retain):
                self.panggilan = (topik, payload, qos, retain)
                return HasilPublikasi()

        state = {
            "timestamp": 123.4,
            "missionState": "RUNNING",
            "position": {"x": 1, "y": 2},
        }
        jembatan = self.modul.MqttBridge()
        jembatan.client = ClientPalsu()
        jembatan.connected.set()
        jembatan.state_terakhir = state

        with patch.object(self.modul, "_debug"):
            jembatan._publish_state()

        topik, payload, qos, dipertahankan = jembatan.client.panggilan
        self.assertEqual(topik, "/sistem_broadcast/state_dan_variabel")
        self.assertEqual(json.loads(payload), state)
        self.assertEqual(qos, 0)
        self.assertFalse(dipertahankan)


if __name__ == "__main__":
    unittest.main()
