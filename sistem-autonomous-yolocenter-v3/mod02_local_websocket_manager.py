"""Broker pub/sub lokal untuk seluruh data panas sistem."""

from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict
from typing import Any

import websockets

import mod01_config as config


pencatat = logging.getLogger("BrokerTopik")


class LocalWebsocketManager:
    """Menyimpan pelanggan dan nilai terakhir setiap topik."""

    def __init__(self) -> None:
        self.pelanggan: dict[str, set[Any]] = defaultdict(set)
        self.nilai_terakhir: dict[str, Any] = {}

    async def berlangganan(self, koneksi: Any, topik: str) -> None:
        self.pelanggan[topik].add(koneksi)
        if topik in self.nilai_terakhir:
            await self._kirim(koneksi, topik, self.nilai_terakhir[topik], True)

    def lepaskan(self, koneksi: Any) -> None:
        for pelanggan_topik in self.pelanggan.values():
            pelanggan_topik.discard(koneksi)

    async def publikasi(self, topik: str, data: Any, dipertahankan: bool) -> None:
        if dipertahankan:
            self.nilai_terakhir[topik] = data

        koneksi_mati = []
        for koneksi in tuple(self.pelanggan.get(topik, ())):
            try:
                await self._kirim(koneksi, topik, data, dipertahankan)
            except websockets.ConnectionClosed:
                koneksi_mati.append(koneksi)

        for koneksi in koneksi_mati:
            self.lepaskan(koneksi)

    @staticmethod
    async def _kirim(koneksi: Any, topik: str, data: Any, dipertahankan: bool) -> None:
        pesan = {
            "aksi": "pesan",
            "topik": topik,
            "data": data,
            "dipertahankan": dipertahankan,
        }
        await koneksi.send(json.dumps(pesan, ensure_ascii=False, separators=(",", ":")))


class WebsocketWorker:
    """Server broker yang menerima perintah subscribe dan publish."""

    def __init__(self, host: str | None = None, port: int | None = None) -> None:
        self.host = host or config.BROKER_HOST
        self.port = port or config.BROKER_PORT
        self.pengelola = LocalWebsocketManager()

    async def tangani_koneksi(self, koneksi: Any) -> None:
        pencatat.info("Klien terhubung: %s", koneksi.remote_address)
        try:
            async for pesan_teks in koneksi:
                await self._tangani_pesan(koneksi, pesan_teks)
        except websockets.ConnectionClosed:
            pass
        finally:
            self.pengelola.lepaskan(koneksi)
            pencatat.info("Klien terputus: %s", koneksi.remote_address)

    async def _tangani_pesan(self, koneksi: Any, pesan_teks: str | bytes) -> None:
        if isinstance(pesan_teks, bytes):
            await koneksi.send(json.dumps({"aksi": "galat", "pesan": "broker hanya menerima JSON"}))
            return

        try:
            pesan = json.loads(pesan_teks)
            aksi = pesan.get("aksi", pesan.get("action"))
            topik = pesan.get("topik", pesan.get("topic"))
            if not isinstance(topik, str) or not topik.startswith("/"):
                raise ValueError("topik harus berupa string yang diawali /")

            if aksi in {"berlangganan", "subscribe"}:
                await self.pengelola.berlangganan(koneksi, topik)
            elif aksi in {"publikasi", "publish"}:
                await self.pengelola.publikasi(
                    topik,
                    pesan.get("data"),
                    bool(pesan.get("dipertahankan", pesan.get("retain", True))),
                )
            else:
                raise ValueError("aksi tidak dikenal")
        except (ValueError, json.JSONDecodeError) as galat:
            await koneksi.send(json.dumps({"aksi": "galat", "pesan": str(galat)}))

    async def jalankan(self) -> None:
        pencatat.info("Broker aktif di ws://%s:%s", self.host, self.port)
        async with websockets.serve(self.tangani_koneksi, self.host, self.port, max_size=8_000_000):
            await asyncio.Future()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    asyncio.run(WebsocketWorker().jalankan())


if __name__ == "__main__":
    main()
