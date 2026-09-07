"""Client pub/sub yang aman dipakai dari proses dan thread biasa."""

from __future__ import annotations

import asyncio
import json
import logging
import queue
import threading
from collections import defaultdict
from typing import Any, Callable

import websockets

import mod01_config as config


TOPIK_MAVLINK = "/local_scope/mavlink/state"
TOPIK_VISION = "/local_scope/vision/state"
TOPIK_FRAME = "/local_scope/vision/frame"
TOPIK_PERINTAH_VISION = "/local_scope/vision/command"
TOPIK_ARENA = "/local_scope/arena/state"
TOPIK_SERIAL = "/local_scope/serial/state"
TOPIK_GUI_STATE = "/local_scope/gui/state"
TOPIK_PERINTAH = "/local_scope/gui/command"

pencatat = logging.getLogger("RobotTopic")
PenanganTopik = Callable[[str, Any], None]


class RobotTopicClient:
    """Menjaga koneksi broker, cache retained, dan antrean publikasi."""

    def __init__(self, alamat: str | None = None) -> None:
        self.alamat = alamat or config.BROKER_URL
        self.langganan: dict[str, list[PenanganTopik]] = defaultdict(list)
        self.nilai: dict[str, Any] = {}
        self.antrean: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=100)
        self.sinyal_berhenti = threading.Event()
        self.sinyal_terhubung = threading.Event()
        self.utas: threading.Thread | None = None
        self.kunci = threading.RLock()

    def mulai(self) -> None:
        if self.utas and self.utas.is_alive():
            return
        self.sinyal_berhenti.clear()
        self.utas = threading.Thread(target=self._jalankan_utas, daemon=True, name="robot-topic")
        self.utas.start()

    def berhenti(self) -> None:
        self.sinyal_berhenti.set()
        if self.utas:
            self.utas.join(timeout=3)

    def berlangganan(self, topik: str, penangan: PenanganTopik | None = None) -> None:
        with self.kunci:
            if penangan and penangan not in self.langganan[topik]:
                self.langganan[topik].append(penangan)
            elif topik not in self.langganan:
                self.langganan[topik] = []
        self._masukkan({"aksi": "berlangganan", "topik": topik})

    def publikasi(self, topik: str, data: Any, dipertahankan: bool = True) -> None:
        self._masukkan({
            "aksi": "publikasi",
            "topik": topik,
            "data": data,
            "dipertahankan": dipertahankan,
        })

    def ambil(self, topik: str, bawaan: Any = None) -> Any:
        with self.kunci:
            return self.nilai.get(topik, bawaan)

    def tunggu_terhubung(self, batas_waktu: float = 5.0) -> bool:
        return self.sinyal_terhubung.wait(batas_waktu)

    def _masukkan(self, pesan: dict[str, Any]) -> None:
        try:
            self.antrean.put_nowait(pesan)
        except queue.Full:
            try:
                self.antrean.get_nowait()
                self.antrean.put_nowait(pesan)
            except queue.Empty:
                pass

    def _jalankan_utas(self) -> None:
        asyncio.run(self._jaga_koneksi())

    async def _jaga_koneksi(self) -> None:
        while not self.sinyal_berhenti.is_set():
            try:
                async with websockets.connect(self.alamat, open_timeout=3, max_size=8_000_000) as koneksi:
                    self.sinyal_terhubung.set()
                    pencatat.info("Terhubung ke %s", self.alamat)
                    with self.kunci:
                        daftar_topik = tuple(self.langganan)
                    for topik in daftar_topik:
                        await koneksi.send(json.dumps({"aksi": "berlangganan", "topik": topik}))

                    penerima = asyncio.create_task(self._terima(koneksi))
                    pengirim = asyncio.create_task(self._kirim(koneksi))
                    selesai, tertunda = await asyncio.wait(
                        {penerima, pengirim}, return_when=asyncio.FIRST_COMPLETED
                    )
                    for tugas in tertunda:
                        tugas.cancel()
                    await asyncio.gather(*selesai, *tertunda, return_exceptions=True)
            except (OSError, TimeoutError, websockets.ConnectionClosed) as galat:
                pencatat.warning("Broker belum tersedia: %s", galat)
            except Exception:
                pencatat.exception("Koneksi broker gagal")
            finally:
                self.sinyal_terhubung.clear()

            if not self.sinyal_berhenti.is_set():
                await asyncio.sleep(1)

    async def _kirim(self, koneksi: Any) -> None:
        while not self.sinyal_berhenti.is_set():
            try:
                pesan = self.antrean.get_nowait()
            except queue.Empty:
                await asyncio.sleep(0.01)
                continue
            await koneksi.send(json.dumps(pesan, ensure_ascii=False, separators=(",", ":")))

    async def _terima(self, koneksi: Any) -> None:
        async for pesan_teks in koneksi:
            pesan = json.loads(pesan_teks)
            if pesan.get("aksi") != "pesan":
                continue
            topik = pesan.get("topik")
            data = pesan.get("data")
            with self.kunci:
                self.nilai[topik] = data
                daftar_penangan = tuple(self.langganan.get(topik, ()))
            for penangan in daftar_penangan:
                try:
                    penangan(topik, data)
                except Exception:
                    pencatat.exception("Penangan topik %s gagal", topik)


robot_topic = RobotTopicClient()
