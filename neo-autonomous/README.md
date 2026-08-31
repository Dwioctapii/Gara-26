# Neo Autonomous

`neo-autonomous` menghubungkan target hasil YOLOv8 dengan kendali gerak
Pixhawk/MAVLink tanpa mengubah folder milik tim YOLO maupun folder `baru-*`.

## Alur data

```text
yolo8/run_pt_video.py
  -> WebSocket target :8770
  -> target_pair_id + bearing_degrees + distance
  -> controller Neo Autonomous
  -> forward speed + yaw rate
  -> MAVLink / Pixhawk
```

YOLO tetap menentukan tepat satu target. Neo tidak memilih pasangan ulang;
Neo mencari object `pairs[]` dengan ID yang sama dengan `target_pair_id`.

## Batas dengan sistem tim lain

Folder `../baru-sistem-autonomous-yolocenter` hanya dibaca sebagai referensi
dan tidak diubah. Pada sistem tersebut, MAVLink dipakai untuk telemetri,
mission, arm, dan pergantian mode. Hasil vision berupa `servo_pwm` justru
dikirim oleh `SerialWorker` ke Teensy; Teensy menulis PWM langsung ke servo.

Neo tidak menyalin jalur Teensy tersebut. Neo mengirim kecepatan maju dan laju
belok langsung ke ArduRover melalui `SET_POSITION_TARGET_LOCAL_NED`. Karena itu:

- Pixhawk harus menjalankan firmware Rover/Boat dan berada di `GUIDED`.
- Servo kemudi dan throttle harus benar-benar dikendalikan output Pixhawk serta
  `SERVOx_FUNCTION`-nya harus sudah benar.
- Jika servo masih hanya terhubung ke pin Teensy seperti desain tim lain,
  perintah MAVLink Neo dapat diterima Pixhawk tetapi tidak akan menggerakkan
  servo tersebut.

## Instalasi dan menjalankan

Pada komputer/board yang tersambung ke Pixhawk:

```bash
cd neo-autonomous
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Cari port Pixhawk yang stabil:

```bash
ls -l /dev/serial/by-id/
```

Jika tepat satu perangkat `*Pixhawk*-if00` ditemukan, Neo akan memilihnya
secara otomatis. Environment `NEO_MAVLINK` tetap dapat dipakai untuk override.

Lalu set environment. Ganti path berikut sesuai hasil pada board:

```bash
export NEO_MAVLINK=/dev/serial/by-id/usb-Holybro_Pixhawk6C_410021001951343034343031-if00
export NEO_MAVLINK_CONTROL_MODE=velocity
export NEO_MAVLINK_REQUIRED_MODE=GUIDED
export NEO_AUTO_SET_GUIDED=1
export NEO_REQUIRE_ARMED=1
export NEO_AUTO_START=0
python3 main.py
```

Cara singkat dengan deteksi port Pixhawk otomatis:

```bash
cd ~/Downloads/sagara/asv-2026/neo-autonomous
bash start.sh
```

Untuk menjalankan Neo dan YOLO sekaligus (ganti `4` dengan nomor kamera yang
benar):

```bash
bash start.sh --camera 4
```

Tambahkan `--show` bila membutuhkan preview. Tanpa `--show`, preview dan
penyimpanan video dimatikan agar performa Jetson tetap tinggi. `Ctrl+C`
menghentikan YOLO dan Neo. Script tidak melakukan arm atau enable autonomy;
setelah pengecekan aman, jalankan `python3 neoctl.py enable` dari terminal lain.

Pada proses YOLOv8 milik tim vision, arahkan output ke WebSocket target Neo:

```bash
cd ../yolo8
python3 run_pt_video.py best.engine CAMERA_ID \
  --backend cuda \
  --ws-url ws://127.0.0.1:8770 \
  --no-save
```

Tidak ada file model yang diduplikasi ke `neo-autonomous`: `best.pt` dan proses
inferensi tetap dimiliki folder `yolo8`; yang menjadi batas integrasi antartim
adalah payload WebSocket tersebut.

Port lain:

- `ws://IP-BOARD:8765`: telemetry dan command operator.
- `http://IP-BOARD:8766/health`: health check.
- `http://IP-BOARD:8766/state`: seluruh state termasuk target dan output kontrol.

## Mengaktifkan kontrol

Default `NEO_AUTO_START=0`, jadi data target masuk tetapi kapal belum bergerak.
Aktifkan melalui WebSocket telemetry:

```json
{"command":"autonomy","action":"enable"}
```

Atau gunakan CLI yang disediakan:

```bash
python3 neoctl.py enable
python3 neoctl.py disable
```

Matikan dengan:

```json
{"command":"autonomy","action":"disable"}
```

Neo tidak pernah melakukan arm otomatis. Dengan default
`NEO_REQUIRE_ARMED=1`, setpoint gerak baru dikirim setelah Pixhawk sudah armed.
Mode MAVLink default adalah body velocity. Pastikan flight mode menerima
setpoint velocity (`GUIDED` pada ArduRover). Jika `NEO_AUTO_SET_GUIDED=1`, Neo
meminta GUIDED tetapi baru mengirim gerak setelah HEARTBEAT mengonfirmasinya.
Neo mengirim heartbeat companion 1 Hz dan menyatakan link putus bila heartbeat
kendaraan hilang selama tiga detik.

`neoctl.py arm`, `disarm`, `guided`, dan `manual` sengaja ditolak kecuali
`NEO_ENABLE_REMOTE_COMMANDS=1`. Untuk pengujian awal, lakukan arm dan pergantian
mode melalui transmitter/Mission Planner; hanya `enable` dan `disable` Neo yang
tetap tersedia tanpa flag tersebut.

Status dapat diperiksa tanpa menggerakkan kapal:

```bash
curl -s http://127.0.0.1:8766/state | python3 -m json.tool
```

Urutan status normal adalah `DISABLED`, lalu setelah autonomy diaktifkan:
`WAITING_FOR_MAVLINK` → `WAITING_FOR_GUIDED` → `WAITING_FOR_ARM` → `TRACKING`.
`TARGET_LOST` berarti koneksi bekerja tetapi target YOLO sudah kedaluwarsa.

## Perilaku kontrol

- Bearing positif dari YOLO berarti target di kanan dan menghasilkan yaw rate
  positif; bearing negatif menghasilkan belok kiri.
- Kecepatan maju mengecil saat mendekati `NEO_STOP_DISTANCE_M`.
- Jika sudut melebihi `NEO_DRIVE_BEARING_LIMIT_DEGREES`, kapal hanya berputar.
- Target kosong atau tidak diperbarui selama
  `NEO_TARGET_TIMEOUT_SECONDS` selalu menghasilkan perintah stop.
- `NEO_MAVLINK_CONTROL_MODE=manual` tersedia bila firmware tidak menerima
  body-velocity setpoint. Uji arah channel di darat sebelum menggunakannya.

Salin nilai dari `.env.example` menjadi environment service di board. File
`.env` tidak dibaca otomatis agar cara deployment (systemd, Docker, shell)
tetap eksplisit.

## Pengujian

```bash
python -m unittest discover -s tests -v
```

Sebelum pengujian air, lakukan pengujian propeller terangkat/dilepas dan cek
bahwa `TARGET_LOST`, `DISABLED`, `WAITING_FOR_GUIDED`, serta `WAITING_FOR_ARM`
menghasilkan nol. Neo tidak pernah melakukan arm otomatis.
