# Sistem Autonomous Waypoint

Backend ini mengintegrasikan pembacaan Pixhawk, sinkronisasi seluruh mission,
dan foto YOLO dari PIS ke dalam kontrak HTTP/WebSocket yang sudah dipakai oleh
`../client/dashboard.js`. Klien web ZIP tidak diubah.

## Jalankan

```bash
cd /home/dwiokta/Downloads/asv-2026/sistem-autonomous-waypoint
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python3 main.py
```

Di terminal kedua, layani klien web ZIP dari board yang sama:

```bash
cd /home/dwiokta/Downloads/asv-2026/client
python3 dev_server.py
```

Buka `http://IP-BOARD:8000/asv-client.html` (atau `index.html` jika itu halaman
yang diinginkan). Karena web dibuka dari IP board, `dashboard.js` yang tidak
diubah akan otomatis tersambung ke `ws://IP-BOARD:8765` dan
`http://IP-BOARD:8766`.

## Data mission

Payload WebSocket mempertahankan `mission.current` dan `mission.total` untuk
dashboard lama, serta menambahkan seluruh koordinat pada `mission.waypoints`:

```json
{
  "mission": {
    "current": 2,
    "total": 5,
    "waypoints": [{"seq": 0, "lat": -6.2, "lon": 106.8, "alt": 10.0}]
  }
}
```

Mission ditarik ulang setiap satu detik. Perubahan yang diunggah dari Mission
Planner akan menggantikan `mission.waypoints` hanya setelah daftar barunya
lengkap diterima.

## Endpoint

- `GET /health`, `/state`, `/status`, `/atas.jpg`, `/bawah.jpg` di port `8766`.
- WebSocket telemetry di port `8765`.

`/status` mengembalikan `{"atas": true, "bawah": true}` agar photo polling
pada web client ZIP berjalan tanpa perubahan.
