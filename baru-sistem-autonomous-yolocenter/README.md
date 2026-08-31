# Sistem Autonomous YOLO Center

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

### Jetson Orin

Engine TensorRT tidak portabel antar-model GPU. Jika muncul warning
`Using an engine plan file across different models of devices`, bangun ulang
`best.engine` langsung pada Orin dari `best.pt`:

```bash
cd ~/Downloads/sagara/asv-2026/baru-sistem-autonomous-yolocenter
bash rebuild_engine.sh
```

Tahap `TensorRT: starting export` dapat terlihat diam selama beberapa menit
karena TensorRT sedang memilih dan mengompilasi kernel. Jangan hentikan dengan
`Ctrl+C`. Skrip mematikan AutoInstall `onnxruntime-gpu` yang memang tidak
tersedia sebagai wheel PyPI biasa untuk Jetson/aarch64, menggunakan workspace
1 GiB, dan memulihkan engine lama jika ekspor gagal atau diinterupsi.

Engine lama tidak dihapus; script menggantinya secara aman menjadi file
`best.engine.perangkat-lama-TIMESTAMP`, mengekspor FP16, lalu melakukan warm-up.
Jika export gagal, engine lama dikembalikan.

Untuk startup dengan port Pixhawk/Teensy stabil dan nomor kamera eksplisit:

```bash
v4l2-ctl --list-devices
bash start.sh --atas 4 --bawah 6
```

Ganti `4` dan `6` sesuai device kamera. Script otomatis memilih:

- `*Pixhawk*-if00` untuk MAVLink;
- `*Teensy*` untuk PWM servo;
- Python environment yang benar-benar dapat mengimpor dependency Jetson.

Override tetap dapat diberikan dengan `ASV_MAVLINK`, `ASV_TEENSY_PORT`,
`ASV_CAM_ATAS`, `ASV_CAM_BAWAH`, `ASV_MODEL_PATH`, atau `ASV_PYTHON`.

### Performa GUI

Preview Matplotlib memakai frame terbaru tanpa menunggu kamera bawah, blitting,
dan cache konversi warna. Default GUI adalah 15 FPS dan telemetry/peta 5 Hz:

```bash
export ASV_GUI_FPS=15
export ASV_GUI_TELEMETRY_HZ=5
export ASV_GUI_BLIT=1
bash start.sh --atas 4 --bawah 6
```

Naikkan `ASV_GUI_FPS=20` bila Jetson masih memiliki ruang CPU. Jika backend
Matplotlib tertentu menampilkan artefak, gunakan `ASV_GUI_BLIT=0`; ini lebih
berat karena seluruh dashboard digambar ulang.

GUI hanya memasukkan artist yang terikat ke axes ke daftar blit. Ini menjaga
kompatibilitas dengan backend GTK lama dan mencegah error
`NoneType ... _get_view` dari teks status PID level-figure.

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
