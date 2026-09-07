"""Fungsi bersama untuk HTTP dan WebSocket worker."""

import base64
import hashlib
import json
import os
import time


DEBUG_ACTIVE = os.getenv("ASV_DEBUG", "1") == "1"
PHOTO_CHUNK_CHARS = max(4096, int(os.getenv("ASV_PHOTO_CHUNK_CHARS", "49152")))
PHOTO_CHUNK_CHARS -= PHOTO_CHUNK_CHARS % 4
PHOTO_CHECK_SECONDS = max(0.1, float(os.getenv("ASV_PHOTO_CHECK_SECONDS", "0.5")))


def _debug(channel: str, event: str, detail=None) -> None:
    if not DEBUG_ACTIVE:
        return
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    value = "" if detail is None else json.dumps(detail, ensure_ascii=False, default=str)
    print(f"[{stamp}][DEBUG][{channel}] {event} {value}")


def _read_photo(path):
    """Baca foto hanya jika file tidak berubah selama proses baca."""
    try:
        before = path.stat()
        content = path.read_bytes()
        after = path.stat()
    except OSError:
        return None
    before_signature = (before.st_mtime_ns, before.st_size)
    after_signature = (after.st_mtime_ns, after.st_size)
    if before_signature != after_signature:
        return None
    return content, after_signature


def _prepare_photo_transfer(camera: str, path, previous_signature):
    result = _read_photo(path)
    if not result:
        return None
    content, signature = result
    if signature == previous_signature:
        return None

    encoded = base64.b64encode(content).decode("ascii")
    chunks = [encoded[index:index + PHOTO_CHUNK_CHARS]
              for index in range(0, len(encoded), PHOTO_CHUNK_CHARS)]
    digest = hashlib.sha256(content).hexdigest()
    metadata = {
        "camera": camera,
        "transfer_id": f"{camera}-{signature[0]}-{digest[:12]}",
        "mime_type": "image/jpeg",
        "total_bytes": len(content),
        "total_chars": len(encoded),
        "total_chunks": len(chunks),
        "sha256": digest,
    }
    return metadata, chunks, signature


def _encode_live_frame(store, quality: int, previous_sequence: int) -> tuple[bytes | None, int]:
    """Ambil satu frame konsisten dan kompres di worker thread."""
    if hasattr(store, "frame_snapshot"):
        frame, sequence = store.frame_snapshot()
    else:
        frame = getattr(store, "live_frame_bgr", None)
        sequence = id(frame)
    if frame is None:
        return None, sequence
    if sequence == previous_sequence:
        return None, sequence
    try:
        import cv2
        ok, encoded = cv2.imencode(
            ".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), quality]
        )
        return (encoded.tobytes() if ok else None), sequence
    except Exception:
        return None, sequence