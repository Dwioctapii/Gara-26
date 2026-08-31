# Sistem Autonomous Waypoint

Backend ini mengintegrasikan pembacaan Pixhawk, sinkronisasi seluruh mission,
dan foto YOLO dari PIS. Seluruh state dashboard, termasuk foto JPEG base64,
dikirim sebagai snapshot JSON lewat WebSocket. HTTP hanya dipakai client untuk
mengirim command dari tombol.

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

## Transport

- `POST /api/command` di port `8766` menerima command JSON dari tombol.
- `GET /health` di port `8766` hanya untuk pemeriksaan proses.
- WebSocket di port `8765` membroadcast snapshot JSON lengkap.

Foto berada pada `photos.atas` dan `photos.bawah` sebagai string base64 atau
`null`. Dashboard selalu mengikuti nilai snapshot; nilai yang hilang atau
`null` mengembalikan tampilan kamera ke placeholder.
