"""WebSocket worker: kirim state, foto, dan terima perintah."""

from __future__ import annotations

import asyncio
import json
import os
import threading
import time

import websockets

from server_common import (
    _debug,
    _encode_live_frame,
    _prepare_photo_transfer,
    PHOTO_CHECK_SECONDS,
)


def start_websocket(host: str, port: int, hz: float, store, photo_dir, command_handler=None) -> None:
    async def client(websocket):
        profile = {
            "state": True,
            "camera": False,
            "photos": False,
            "state_hz": max(1.0, min(float(hz), 30.0)),
            "camera_hz": max(1.0, min(float(os.getenv("ASV_CAMERA_WS_HZ", "15")), 30.0)),
            "jpeg_quality": max(35, min(int(os.getenv("ASV_CAMERA_JPEG_QUALITY", "75")), 95)),
            "component": "legacy",
        }
        send_lock = asyncio.Lock()

        async def send(payload):
            async with send_lock:
                await websocket.send(payload)

        async def send_photos(previous_photos: dict) -> dict:
            availability = {}
            for camera in ("atas", "bawah"):
                path = photo_dir / f"{camera}.jpg"
                availability[camera] = path.is_file()
                if not availability[camera]:
                    previous_photos.pop(camera, None)
                    continue

                prepared = await asyncio.get_running_loop().run_in_executor(
                    None, _prepare_photo_transfer,
                    camera, path, previous_photos.get(camera)
                )
                if not prepared:
                    continue
                metadata, chunks, signature = prepared
                transfer_id = metadata["transfer_id"]
                digest = metadata["sha256"]
                _debug("WS-PHOTO", "transfer_started", metadata)
                await send(json.dumps({"type": "photo_start", **metadata}, separators=(",", ":")))
                for index, chunk in enumerate(chunks):
                    chunk_data = {
                        "type": "photo_chunk",
                        "camera": camera,
                        "transfer_id": transfer_id,
                        "index": index,
                        "total_chunks": len(chunks),
                        "data": chunk,
                    }
                    await send(json.dumps(chunk_data, separators=(",", ":")))
                    _debug("WS-PHOTO", "chunk_sent", {
                        "camera": camera,
                        "transfer_id": transfer_id,
                        "index": index,
                        "total_chunks": len(chunks),
                        "base64_chars": len(chunk),
                    })
                await send(json.dumps({
                    "type": "photo_end",
                    "camera": camera,
                    "transfer_id": transfer_id,
                    "sha256": digest,
                }, separators=(",", ":")))
                previous_photos[camera] = signature
                _debug("WS-PHOTO", "transfer_finished", metadata)
            await send(json.dumps({"type": "photo_status", **availability}, separators=(",", ":")))
            return previous_photos

        async def tx():
            next_state = 0.0
            next_camera = 0.0
            next_photos = 0.0
            frame_sequence = -1
            previous_photos = {}
            while True:
                now = time.monotonic()
                if profile["state"] and now >= next_state:
                    snapshot = store.snapshot()
                    await send(json.dumps(snapshot, separators=(",", ":")))
                    _debug("WS-DATA", "state_sent", snapshot)
                    next_state = now + 1.0 / profile["state_hz"]
                if profile["camera"] and now >= next_camera:
                    frame, frame_sequence = await asyncio.get_running_loop().run_in_executor(
                        None, _encode_live_frame, store, profile["jpeg_quality"], frame_sequence
                    )
                    if frame:
                        await send(frame)
                        _debug("WS-CAMERA", "binary_frame_sent", {"bytes": len(frame)})
                    next_camera = now + 1.0 / profile["camera_hz"]
                if profile["photos"] and now >= next_photos:
                    previous_photos = await send_photos(previous_photos)
                    next_photos = now + PHOTO_CHECK_SECONDS
                await asyncio.sleep(0.005)
        
        async def rx():
            async for raw in websocket:
                cmd = None
                try:
                    if isinstance(raw, bytes):
                        raise ValueError("client tidak boleh mengirim data biner")
                    cmd = json.loads(raw)
                    if isinstance(cmd, dict) and cmd.get("type") == "subscribe":
                        profile["state"] = bool(cmd.get("state", True))
                        profile["camera"] = bool(cmd.get("camera", False))
                        profile["photos"] = bool(cmd.get("photos", False))
                        profile["state_hz"] = max(1.0, min(float(cmd.get("state_hz", hz)), 30.0))
                        profile["camera_hz"] = max(1.0, min(float(cmd.get("camera_hz", 15.0)), 30.0))
                        profile["jpeg_quality"] = max(35, min(int(cmd.get("jpeg_quality", 75)), 95))
                        profile["component"] = str(cmd.get("component", "unknown"))[:40]
                        subscription = {
                            "type": "subscribed",
                            "component": profile["component"],
                            "state": profile["state"],
                            "camera": profile["camera"],
                            "photos": profile["photos"],
                        }
                        _debug("WS", "subscription_received", subscription)
                        await send(json.dumps(subscription))
                        continue
                    if not isinstance(cmd, dict) or not isinstance(cmd.get("command"), str):
                        raise ValueError("invalid command")
                    
                    _debug("WS-COMMAND", "request_received", cmd)
                    store.command(cmd)
                    
                    result = None
                    if command_handler:
                        result = await asyncio.get_running_loop().run_in_executor(
                            None, command_handler, cmd
                        )
                        
                    ack = {"type": "ack", "id": cmd.get("id"), "ok": True, "result": result}
                    await send(json.dumps(ack))
                    _debug("WS-COMMAND", "ack_sent", ack)
                except Exception as exc:
                    ack = {"type": "ack", "id": cmd.get("id") if isinstance(cmd, dict) else None, "ok": False, "error": str(exc)}
                    await send(json.dumps(ack))
                    _debug("WS-COMMAND", "request_failed", ack)
                    
        tasks = {asyncio.create_task(tx()), asyncio.create_task(rx())}
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        results = await asyncio.gather(*tasks, return_exceptions=True)
        errors = [str(result) for result in results if isinstance(result, Exception)]
        _debug("WS", "client_disconnected", {
            "component": profile["component"],
            "errors": errors,
        })

    async def run():
        async with websockets.serve(client, host, port, ping_interval=20, ping_timeout=20, max_size=1_000_000):
            print(f"[WS] ws://{host}:{port}")
            await asyncio.Future()

    threading.Thread(target=lambda: asyncio.run(run()), daemon=True, name="websocket").start()