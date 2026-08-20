# ASV server

Server menyatukan telemetri MAVLink, dashboard WebSocket, HTTP camera snapshots,
hasil object detection, command, state persisten, dan CSV logger.

```bash
python -m venv .venv
# Linux/macOS: source .venv/bin/activate
# Windows: .venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

Default: WebSocket `:8765`, HTTP `:8766`, MAVLink UDP `:14550`.
Command kendaraan dinonaktifkan secara default. Aktifkan hanya setelah pengujian
tanpa propeller dengan environment `ASV_ENABLE_COMMANDS=1`.

HTTP API:

- `GET /health`, `/state`, `/status`, `/atas.jpg`, `/bawah.jpg`
- `POST /api/state` — JSON patch dari sensor/service lain
- `POST /api/detections` — JSON hasil vision
- `POST /api/photo/atas` atau `/api/photo/bawah` — body JPEG

Data runtime berada di `server/data/`.
