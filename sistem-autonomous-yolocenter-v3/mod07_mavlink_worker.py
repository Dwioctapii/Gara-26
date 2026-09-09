from __future__ import annotations

import logging
import math
import os
import threading
import time
from pymavlink import mavutil
import mod01_config as config
from mod03_robot_topic import TOPIK_MAVLINK, TOPIK_PERINTAH, robot_topic
from mod05_state_manager import state

pencatat = logging.getLogger("MavlinkWorker")

NAMA_TOPIK = TOPIK_MAVLINK


class MavlinkPublisher:
    """Adapter agar parser MAVLink hanya menerbitkan hot data."""

    def update(self, data_baru: dict) -> None:
        robot_topic.publikasi(TOPIK_MAVLINK, data_baru)

    def replace_mission(self, daftar_waypoint: list[dict]) -> bool:
        waypoint_tersimpan = state.baca()["mission"]["waypoints"]
        berubah = waypoint_tersimpan != daftar_waypoint
        if berubah:
            state.ganti_misi(daftar_waypoint)
        self.update({"mission": {"current": 0, "total": len(daftar_waypoint)}})
        return berubah


class MavlinkWorker:
    def __init__(self, titik_koneksi: str, baud: int, jeda_refresh: float, penyimpanan) -> None:
        self.titik_koneksi, self.baud, self.jeda_refresh, self.penyimpanan = titik_koneksi, baud, jeda_refresh, penyimpanan
        self.koneksi_utama = None
        self.sinyal_berhenti = threading.Event()
        self.permintaan_terakhir = 0.0
        self.sedang_mengunduh = False
        self.total_tertunda = 0
        self.daftar_waypoint_tertunda: list[dict] = []
        self.heartbeat_terakhir = 0.0

    def mulai(self) -> None:
        threading.Thread(target=self._jalankan, daemon=True, name="mavlink").start()

    def berhenti(self) -> None:
        self.sinyal_berhenti.set()
        if self.koneksi_utama:
            self.koneksi_utama.close()

    def _publikasi(self, data_baru: dict) -> None:
        """Terbitkan perubahan telemetri ke hot topic."""
        self.penyimpanan.update(data_baru)

    def _jalankan(self) -> None:
        while not self.sinyal_berhenti.is_set():
            try:
                pencatat.info(f"[MAVLINK] Menghubungkan ke {self.titik_koneksi}...")
                self.koneksi_utama = mavutil.mavlink_connection(self.titik_koneksi, baud=self.baud)
                if self.koneksi_utama.wait_heartbeat(timeout=10) is None:
                    raise TimeoutError("waktu koneksi heartbeat habis")
                
                pencatat.info(f"[MAVLINK] Terhubung ke sistem {self.koneksi_utama.target_system}")
                self.heartbeat_terakhir = time.monotonic()
                
                # Minta stream data pada kecepatan tinggi (20 Hz)
                self.koneksi_utama.mav.request_data_stream_send(
                    self.koneksi_utama.target_system,
                    self.koneksi_utama.target_component,
                    mavutil.mavlink.MAV_DATA_STREAM_ALL,
                    20,
                    1,
                )
                
                self._publikasi({"connected": True, "lastError": None, "sensors": {"heartbeat": True}})
                self._minta_misi()

                # Loop cepat non-blocking (secepat tester)
                while not self.sinyal_berhenti.is_set():
                    if time.monotonic() - self.heartbeat_terakhir > 5:
                        raise ConnectionError("heartbeat MAVLink hilang lebih dari 5 detik")
                    if self.sedang_mengunduh and time.monotonic() - self.permintaan_terakhir > 10:
                        pencatat.warning("Unduh misi timeout; akan dicoba ulang")
                        self.sedang_mengunduh = False
                    if time.monotonic() - self.permintaan_terakhir >= self.jeda_refresh and not self.sedang_mengunduh:
                        self._minta_misi()

                    while True:
                        pesan = self.koneksi_utama.recv_match(blocking=False)
                        if pesan is None:
                            break
                        self._proses_pesan(pesan)

                    time.sleep(0.002) # Jeda tipis agar CPU tidak meledak
            except Exception as kesalahan:
                self._publikasi({"connected": False, "lastError": f"MAVLink: {kesalahan}", "sensors": {"heartbeat": False}})
                self.sedang_mengunduh = False
                if not self.sinyal_berhenti.is_set():
                    time.sleep(2)

    def _minta_misi(self) -> None:
        self.permintaan_terakhir, self.sedang_mengunduh = time.monotonic(), True
        try:
            self.koneksi_utama.mav.mission_request_list_send(self.koneksi_utama.target_system, self.koneksi_utama.target_component, mavutil.mavlink.MAV_MISSION_TYPE_MISSION)
        except TypeError:
            self.koneksi_utama.mav.mission_request_list_send(self.koneksi_utama.target_system, self.koneksi_utama.target_component)

    def _minta_item_misi(self, urutan: int) -> None:
        try:
            self.koneksi_utama.mav.mission_request_int_send(self.koneksi_utama.target_system, self.koneksi_utama.target_component, urutan, mavutil.mavlink.MAV_MISSION_TYPE_MISSION)
        except TypeError:
            self.koneksi_utama.mav.mission_request_int_send(self.koneksi_utama.target_system, self.koneksi_utama.target_component, urutan)

    def _proses_pesan(self, pesan) -> None:
        tipe_pesan = pesan.get_type()
        
        if tipe_pesan == "HEARTBEAT":
            self.heartbeat_terakhir = time.monotonic()
            if pesan.get_srcComponent() == 1:
                aktif = bool(pesan.base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED)
                self._publikasi({"mode": (self.koneksi_utama.flightmode or "TIDAK_DIKETAHUI").upper(), "arm": "Armed" if aktif else "Disarmed"})

        elif tipe_pesan == "ATTITUDE":
            self._publikasi({
                "orientation": {"x": pesan.roll, "y": pesan.pitch, "z": pesan.yaw, "w": 1.0},
                "angular": {"x": pesan.rollspeed, "y": pesan.pitchspeed, "z": pesan.yawspeed}
            })

        elif tipe_pesan == "GLOBAL_POSITION_INT":
            kecepatan = math.hypot(pesan.vx / 100.0, pesan.vy / 100.0)
            self._publikasi({
                "gps": {"lat": pesan.lat / 1e7, "lon": pesan.lon / 1e7, "fix": pesan.lat != 0 and pesan.lon != 0},
                "linear": {"x": pesan.vx / 100.0, "y": pesan.vy / 100.0, "z": pesan.vz / 100.0},
                "speed": kecepatan,
                "position": {"z": pesan.relative_alt / 1000.0}
            })

        elif tipe_pesan == "LOCAL_POSITION_NED":
            self._publikasi({"position": {"x": pesan.y, "y": pesan.x, "z": -pesan.z}})

        elif tipe_pesan == "GPS_RAW_INT":
            hdop = 99.9 if pesan.eph == 65535 else pesan.eph / 100.0
            data_gps = {"satellites": pesan.satellites_visible, "hdop": hdop, "fix": pesan.fix_type >= 3}
            if pesan.vel != 65535: data_gps["sog"] = pesan.vel / 100.0
            if pesan.cog != 65535: data_gps["cog"] = pesan.cog / 100.0
            self._publikasi({"gps": data_gps})

        elif tipe_pesan == "SYS_STATUS":
            self._publikasi({"battery1": {"voltage": max(0, pesan.voltage_battery) / 1000.0, "current": max(0, pesan.current_battery) / 100.0}})

        elif tipe_pesan == "BATTERY_STATUS":
            sel_baterai = [v for v in pesan.voltages if v not in (0, 65535)]
            self._publikasi({
                "battery1": {
                    "voltage": sum(sel_baterai) / 1000.0,
                    "current": max(0, pesan.current_battery) / 100.0,
                    "used": max(0, pesan.current_consumed),
                    "temp": 0 if pesan.temperature == 32767 else pesan.temperature / 100.0
                }
            })

        elif tipe_pesan == "SERVO_OUTPUT_RAW":
            self._publikasi({"servo": [pesan.servo1_raw, pesan.servo2_raw, pesan.servo3_raw, pesan.servo4_raw]})

        elif tipe_pesan == "MISSION_CURRENT":
            total = getattr(pesan, "total", 0)
            data_misi = {"mission": {"current": pesan.seq}}
            if total not in (0, 65535): data_misi["mission"]["total"] = total
            self._publikasi(data_misi)

        elif tipe_pesan == "MISSION_COUNT":
            self.total_tertunda, self.daftar_waypoint_tertunda = pesan.count, []
            if pesan.count:
                self._minta_item_misi(0)
            else:
                self.penyimpanan.replace_mission([])
                self.sedang_mengunduh = False

        elif tipe_pesan in ("MISSION_ITEM_INT", "MISSION_ITEM"):
            self._simpan_item_misi(pesan, tipe_pesan == "MISSION_ITEM_INT")

    def tangani_perintah(self, perintah: dict) -> dict:
        nama, aksi = perintah.get("command"), perintah.get("action")
        perintah_perangkat = nama in {"arm", "set_mode", "go_home", "hold_position", "set_home"} or (nama == "mission" and aksi == "start")
        
        if not perintah_perangkat:
            return {"terkirim": False, "alasan": "perintah khusus status"}

        if os.getenv("ASV_ENABLE_COMMANDS", "0") != "1":
            return {"terkirim": False, "alasan": "ASV_ENABLE_COMMANDS=0"}

        if self.koneksi_utama is None:
            raise RuntimeError("MAVLink belum terhubung")

        peta_mode = self.koneksi_utama.mode_mapping() or {}

        if nama == "arm":
            if aksi == "estop":
                self.koneksi_utama.mav.command_long_send(self.koneksi_utama.target_system, self.koneksi_utama.target_component, mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM, 0, 0, 21196, 0, 0, 0, 0, 0)
            elif aksi == "arm":
                self.koneksi_utama.arducopter_arm()
            else:
                self.koneksi_utama.arducopter_disarm()
        elif nama in ("set_mode", "go_home", "hold_position"):
            mode = {"Manual": "MANUAL", "Auto": "AUTO", "Return Home": "RTL"}.get(perintah.get("mode")) if nama == "set_mode" else ("RTL" if nama == "go_home" else ("LOITER" if "LOITER" in peta_mode else "HOLD"))
            if mode not in peta_mode:
                raise ValueError(f"mode {mode} tidak tersedia")
            self.koneksi_utama.set_mode(peta_mode[mode])
        elif nama == "mission" and aksi == "start":
            self.koneksi_utama.mav.command_long_send(self.koneksi_utama.target_system, self.koneksi_utama.target_component, mavutil.mavlink.MAV_CMD_MISSION_START, 0, 0, 0, 0, 0, 0, 0, 0)
        elif nama == "set_home":
            self.koneksi_utama.mav.command_long_send(self.koneksi_utama.target_system, self.koneksi_utama.target_component, mavutil.mavlink.MAV_CMD_DO_SET_HOME, 0, 1, 0, 0, 0, 0, 0, 0)
        
        return {"terkirim": True}

    def _simpan_item_misi(self, pesan, berupa_integer: bool) -> None:
        nama_frame = ("MAV_FRAME_GLOBAL", "MAV_FRAME_GLOBAL_RELATIVE_ALT", "MAV_FRAME_GLOBAL_TERRAIN_ALT", "MAV_FRAME_GLOBAL_INT", "MAV_FRAME_GLOBAL_RELATIVE_ALT_INT", "MAV_FRAME_GLOBAL_TERRAIN_ALT_INT")
        frame_global = {getattr(mavutil.mavlink, nama) for nama in nama_frame if hasattr(mavutil.mavlink, nama)}
        adalah_global = pesan.frame in frame_global
        
        waypoint = {
            "seq": pesan.seq, "command": pesan.command, "frame": pesan.frame,
            "lat": pesan.x / 1e7 if berupa_integer and adalah_global else (pesan.x if adalah_global else None),
            "lon": pesan.y / 1e7 if berupa_integer and adalah_global else (pesan.y if adalah_global else None),
            "alt": pesan.z, "param1": pesan.param1, "param2": pesan.param2,
            "param3": pesan.param3, "param4": pesan.param4,
            "autocontinue": bool(pesan.autocontinue),
        }
        self.daftar_waypoint_tertunda = [item for item in self.daftar_waypoint_tertunda if item["seq"] != pesan.seq]
        self.daftar_waypoint_tertunda.append(waypoint)
        self.daftar_waypoint_tertunda.sort(key=lambda item: item["seq"])

        if pesan.seq + 1 < self.total_tertunda:
            self._minta_item_misi(pesan.seq + 1)
        else:
            misi_berubah = self.penyimpanan.replace_mission(self.daftar_waypoint_tertunda)
            self.sedang_mengunduh = False
            if misi_berubah:
                pencatat.info(f"[MAVLINK] Misi tersinkron: {len(self.daftar_waypoint_tertunda)} item")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    penerbit = MavlinkPublisher()
    worker = MavlinkWorker(
        config.MAVLINK_ENDPOINT,
        config.MAVLINK_BAUD,
        config.MISSION_REFRESH_SECONDS,
        penerbit,
    )
    robot_topic.berlangganan(TOPIK_PERINTAH, lambda _topik, data: worker.tangani_perintah(data))
    robot_topic.mulai()
    worker.mulai()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        worker.berhenti()
        robot_topic.berhenti()


if __name__ == "__main__":
    main()
