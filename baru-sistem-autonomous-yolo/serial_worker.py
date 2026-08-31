"""
Pengirim data ke Teensy via serial binary.

Protokol paket (5 byte):
  [0] 0xAA          — sync header
  [1] PWM low byte  — servo_pwm & 0xFF
  [2] PWM high byte — servo_pwm >> 8
  [3] mode byte     — 0=MANUAL 1=AUTO 2=HOLD 0xFF=DISCONNECT
  [4] XOR checksum  — byte[1] ^ byte[2] ^ byte[3]

Strategi pengiriman:
  - Kirim SEGERA jika servo_pwm atau mode berubah (latensi max ~5ms)
  - Kirim heartbeat setiap 100ms meski nilai sama (Teensy tidak kehilangan state)
  - Auto-reconnect jika serial terputus
"""

import struct
import threading
import time

try:
    import serial
    SERIAL_AVAILABLE = True
except ImportError:
    SERIAL_AVAILABLE = False


# Mapping mode string (dari store) → byte yang dikirim ke Teensy
_MODE_MAP = {
    "MANUAL":       0x00,
    "AUTO":         0x01,
    "HOLD":         0x02,
    "LOITER":       0x02,
    "GUIDED":       0x02,
    "STABILIZE":    0x00,
}
_MODE_DISCONNECT = 0xFF


def _mode_to_byte(mode_str: str) -> int:
    """Konversi mode string ke byte. Fallback ke 0xFF jika tidak dikenal."""
    return _MODE_MAP.get(str(mode_str).upper(), _MODE_DISCONNECT)


def _build_packet(pwm: int, mode_byte: int) -> bytes:
    """
    Bangun paket binary 5 byte.

    Struktur:
      0xAA | PWM_LO | PWM_HI | MODE | XOR(PWM_LO, PWM_HI, MODE)
    """
    lo   = pwm & 0xFF
    hi   = (pwm >> 8) & 0xFF
    csum = lo ^ hi ^ mode_byte
    return bytes([0xAA, lo, hi, mode_byte, csum])


class SerialWorker:
    """
    Worker thread yang membaca store['buoy']['servo_pwm'] dan store['mode'],
    lalu mengirimkannya ke Teensy via serial binary dengan latensi minimal.
    """

    def __init__(self, port: str, baud: int, store) -> None:
        self.port  = port
        self.baud  = baud
        self.store = store

        self._ser: "serial.Serial | None" = None
        self._stop = threading.Event()

    def start(self) -> None:
        threading.Thread(target=self._run, daemon=True, name="serial_teensy").start()

    def stop(self) -> None:
        self._stop.set()
        if self._ser and self._ser.is_open:
            self._ser.close()

    # ─────────────────────────────────────────────────────────────────────────
    # Loop utama
    # ─────────────────────────────────────────────────────────────────────────

    def _run(self) -> None:
        if not SERIAL_AVAILABLE:
            print("[SERIAL] pyserial tidak terinstall — serial ke Teensy dinonaktifkan.")
            print("[SERIAL] Install dengan: pip install pyserial")
            self.store.update({"serial": {"connected": False, "error": "pyserial not installed"}})
            return

        HEARTBEAT_INTERVAL = 0.10   # 100ms → kirim ulang meski tidak ada perubahan
        POLL_SLEEP         = 0.005  # 5ms  → cek store 200x/detik (latensi max 5ms)
        RECONNECT_DELAY    = 2.0    # tunggu 2 detik sebelum reconnect

        last_pwm    = -1      # nilai terakhir yang terkirim (−1 = belum pernah kirim)
        last_mode_b = -1
        last_sent   = 0.0

        while not self._stop.is_set():
            # ── (Re)connect jika belum terhubung ─────────────────────────────
            if self._ser is None or not self._ser.is_open:
                try:
                    self._ser = serial.Serial(self.port, self.baud, timeout=0)
                    print(f"[SERIAL] Terhubung ke Teensy di {self.port} @ {self.baud} baud")
                    self.store.update({
                        "serial": {"connected": True, "port": self.port, "error": None}
                    })
                    # Reset agar kirim ulang nilai saat reconnect
                    last_pwm = last_mode_b = -1
                except Exception as exc:
                    self.store.update({
                        "serial": {"connected": False, "port": self.port, "error": str(exc)}
                    })
                    print(f"[SERIAL] Gagal terhubung ke {self.port}: {exc}")
                    time.sleep(RECONNECT_DELAY)
                    continue

            # ── Baca nilai terkini dari store ─────────────────────────────────
            # Akses langsung ke dict (tanpa deepcopy) — sangat ringan.
            data      = self.store.data
            pwm       = int(data.get("buoy", {}).get("servo_pwm", 1500))
            mode_str  = data.get("mode", "DISCONNECTED")
            mode_byte = _mode_to_byte(mode_str)

            now       = time.monotonic()
            changed   = (pwm != last_pwm) or (mode_byte != last_mode_b)
            heartbeat = (now - last_sent) >= HEARTBEAT_INTERVAL

            # ── Kirim jika berubah ATAU heartbeat jatuh tempo ─────────────────
            if changed or heartbeat:
                try:
                    packet = _build_packet(pwm, mode_byte)
                    self._ser.write(packet)
                    last_pwm    = pwm
                    last_mode_b = mode_byte
                    last_sent   = now

                    # Update state store (untuk ditampilkan di GUI / WebSocket)
                    self.store.update({
                        "serial": {
                            "connected":   True,
                            "last_pwm":    pwm,
                            "last_mode_b": mode_byte,
                            "last_mode":   mode_str,
                        }
                    })
                except Exception as exc:
                    print(f"[SERIAL] Error kirim: {exc}")
                    self.store.update({
                        "serial": {"connected": False, "error": str(exc)}
                    })
                    try:
                        self._ser.close()
                    except Exception:
                        pass
                    self._ser = None
                    time.sleep(RECONNECT_DELAY)
                    continue

            time.sleep(POLL_SLEEP)
