import os
import signal
import sys
import unittest
from unittest.mock import Mock, patch

import main


class ProcessSupervisorTest(unittest.TestCase):
    def test_mqtt_aktif_secara_default(self):
        self.assertTrue(main.config.MQTT_ENABLED)
        self.assertTrue(main.config.MQTT_HOST)
        self.assertTrue(main.config.MQTT_USER)
        self.assertTrue(main.config.MQTT_PASS)

    def test_mqtt_mengikuti_konfigurasi_default(self):
        with patch.object(sys, "argv", ["main.py"]):
            with patch.object(main, "jalankan", return_value=0) as jalankan:
                main.main()

        jalankan.assert_called_once_with(False, main.config.MQTT_ENABLED)

    def test_mqtt_dapat_dimatikan_dari_cli(self):
        with patch.object(sys, "argv", ["main.py", "--tanpa-mqtt"]):
            with patch.object(main, "jalankan", return_value=0) as jalankan:
                main.main()

        jalankan.assert_called_once_with(False, False)

    def test_worker_hanya_direstart_satu_kali(self):
        proses_awal = Mock(pid=101, stdout=None)
        proses_awal.poll.return_value = 1
        proses_retry = Mock(pid=102, stdout=None)
        proses_retry.poll.return_value = 2
        pengawas = main.ProcessSupervisor()

        with patch.object(main.subprocess, "Popen", side_effect=[proses_awal, proses_retry]) as pembuat:
            with patch.object(pengawas, "_hentikan_proses"):
                with patch.object(main.time, "sleep"):
                    pengawas.mulai_berkas("tes", "mod12_server_common.py")
                    with self.assertRaisesRegex(RuntimeError, "batas retry habis"):
                        pengawas.pantau()

        self.assertEqual(pembuat.call_count, 2)
        self.assertEqual(pengawas.proses[0].jumlah_restart, 1)

    def test_ctrl_c_selalu_memanggil_penghentian_semua_worker(self):
        pengawas = Mock()
        pengawas.pantau.side_effect = KeyboardInterrupt

        with patch.object(main, "ProcessSupervisor", return_value=pengawas):
            hasil = main.jalankan(tanpa_gui=True, aktifkan_mqtt=False)

        self.assertEqual(hasil, 0)
        pengawas.berhenti.assert_called_once_with()

    def test_worker_gagal_setelah_retry_menghentikan_semua_worker(self):
        pengawas = Mock()
        pengawas.pantau.side_effect = RuntimeError("batas retry habis")

        with patch.object(main, "ProcessSupervisor", return_value=pengawas):
            hasil = main.jalankan(tanpa_gui=True, aktifkan_mqtt=False)

        self.assertEqual(hasil, 1)
        pengawas.berhenti.assert_called_once_with()

    @unittest.skipIf(os.name == "nt", "process group POSIX")
    def test_process_group_menerima_term_dan_kill(self):
        proses = Mock(pid=103)
        spesifikasi = main.ManagedProcess("tes", "tes.py", ["python", "tes.py"], proses)

        with patch.object(main.os, "killpg") as kirim_sinyal:
            main.ProcessSupervisor._hentikan_proses(spesifikasi, paksa=False)
            main.ProcessSupervisor._hentikan_proses(spesifikasi, paksa=True)

        kirim_sinyal.assert_any_call(103, signal.SIGTERM)
        kirim_sinyal.assert_any_call(103, signal.SIGKILL)


if __name__ == "__main__":
    unittest.main()
