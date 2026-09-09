# Peta Sistem Autonomous YOLOCenter

Dokumen ini adalah pintu masuk utama sebelum membaca kode.

## 1. Aturan arsitektur

- Semua worker berjalan sebagai proses Python terpisah dan paralel.
- `main.py` hanya mengurutkan, memantau, memberi label output, dan menghentikan proses.
- Data panas tidak ditulis ke JSON. Data panas selalu lewat pub/sub `robot_topic`.
- Data dingin selalu lewat `mod05_state_manager.py`, langsung ke `data/state.json` dengan file lock.
- Nama class memakai bahasa Inggris. Nama variabel dan penjelasan memakai bahasa Indonesia.
- Folder `sistem-autonomous-yolocenter-old` hanya referensi perilaku, bukan bagian runtime.

## 2. Urutan proses

1. `mod02_local_websocket_manager.py` menyalakan broker pub/sub.
2. `mod09_broadcast_ws_client_worker.py` menggabungkan hot topic dan cold state.
3. `mod07_mavlink_worker.py` membaca autopilot dan menerima perintah perangkat.
4. `mod102_arena_worker.py` memetakan GPS, merekam trajectory, dan menerbitkan JSON arena.
5. `mod06_serial_worker.py` membaca hot topic lalu mengirim kendali ke Teensy.
6. `mod08_vision_worker.py` menjalankan kamera, YOLO, PID, dan publikasi frame.
7. `mod11_http_worker.py` menyediakan health, foto hasil deteksi, dan jalur perintah HTTP.
8. `../client/server_client.py` menyediakan dashboard web pada port 8767.
9. `gui` membuka frontend desktop lama dengan backend RobotTopic.
10. `mod10_broadcast_mqtt_worker.py` aktif otomatis ketika konfigurasi MQTT lengkap. Gunakan `--tanpa-mqtt` hanya untuk debugging offline.

Jika satu worker mati, `main.py` me-restart worker tersebut satu kali. Jika worker hasil restart mati lagi, seluruh process group dihentikan. `Ctrl+C` juga menutup semua worker dan memaksa kill proses yang belum berhenti setelah tiga detik.

## 3. Aliran data panas

Broker: `ws://127.0.0.1:8765` dari sisi client.

| Topik | Penerbit | Pelanggan | Isi |
|---|---|---|---|
| `/local_scope/mavlink/state` | MAVLink | GUI-state, Serial | Telemetri dan status autopilot |
| `/local_scope/vision/state` | Vision | GUI-state, Serial | Deteksi buoy dan keluaran PID |
| `/local_scope/vision/frame` | Vision | GUI Camera | JPEG base64 live, tidak retained |
| `/local_scope/vision/command` | HTTP | Vision | Tahan, ambil langsung, atau reset foto |
| `/local_scope/arena/state` | Arena | GUI-state | Arena A/B, posisi sekarang, dan riwayat trajectory |
| `/local_scope/serial/state` | Serial | GUI-state | Status koneksi dan paket terakhir |
| `/local_scope/gui/state` | GUI-state | GUI desktop, dashboard web, MQTT | Snapshot lengkap untuk frontend |
| `/local_scope/gui/command` | GUI, HTTP | MAVLink, GUI-state | Perintah operator |

Broker menyimpan nilai terakhir topik retained. Subscriber yang baru tersambung langsung menerima nilai terakhir.

## 4. Data dingin

Lokasi baku: `data/state.json`.

Isi yang boleh disimpan:

- `pid_config`
- `currentTrack`
- `home`
- `loggerActive`
- `tahan_foto`
- `missionState`, status trigger arena dari command misi, bukan mode kendaraan
- `mission.waypoints`
- `foto.atas` dan `foto.bawah`, berisi status ketersediaan dan revisi
- `arena.posisi_acuan`, berisi titik mulai arena, GPS, dan heading yang dikunci otomatis saat misi mulai
- `arena.set_dock_sekarang`, berisi latitude dan longitude saat trigger mulai diterima
- `arena.acuan_terkunci`, mencegah acuan berubah selama satu sesi misi

Semua baca/tulis harus melalui singleton `state` dari `mod05_state_manager.py`. Penulisan memakai file sementara lalu `os.replace`, sehingga JSON tidak setengah tertulis ketika listrik atau proses terputus.

## 5. Tanggung jawab modul

- `mod01_config.py`: seluruh konfigurasi runtime dan environment variable.
- `mod02_local_websocket_manager.py`: broker saja; tidak memahami isi data robot.
- `mod03_robot_topic.py`: API publish, subscribe, reconnect, antrean, dan cache retained.
- `mod04_state_content.py`: bentuk default hot data dan cold data.
- `mod05_state_manager.py`: cold JSON dan lock lintas proses.
- `mod06_serial_worker.py`: satu-satunya pengirim paket kendali ke Teensy.
- `mod07_mavlink_worker.py`: satu-satunya pembaca/penulis autopilot.
- `mod08_vision_worker.py`: kamera, deteksi, PID, penyimpanan foto, dan live frame lokal.
- `mod09_broadcast_ws_client_worker.py`: penggabung data untuk seluruh frontend.
- `mod10_broadcast_mqtt_worker.py`: bridge state cloud opsional; tidak mengirim foto.
- `mod11_http_worker.py`: HTTP untuk command, health, dan foto hasil deteksi.
- `mod102_arena_worker.py`: pemilik pemetaan arena, posisi sekarang, dan riwayat trajectory.
- `../client/server_client.py`: HTTP statis dashboard web; tidak menangani API robot.
- `../client/secret.html`: panel kendali internal yang hanya dilayani melalui route `/secret` pada server client.
- `mod12_server_common.py`: format debug worker jaringan.
- `gui/`: frontend desktop lama; backend-nya hanya memakai RobotTopic.
- `../client/dashboard.js`: frontend web; state lokal dari RobotTopic, fallback state dari MQTT, foto dari HTTP.
- `mod100_kalibrasi_box.py`: alat manual kalibrasi model/kamera.
- `mod101_virtual_gps_mapper.py`: konversi koordinat virtual dan GPS.

### Algoritma vision aktif

1. Dua `ThreadedCamera` terus menyimpan frame terbaru kamera atas dan bawah. Loop YOLO tidak menunggu pembacaan USB secara berurutan.
2. Kedua kamera berjalan tetap pada 640×480 dan YOLO memakai `imgsz=640`. Nilai 640 dikunci dan tidak boleh diturunkan menjadi 320. TensorRT diprioritaskan; jika gagal dimuat, worker mencoba model `.pt`.
3. Bounding box digambar manual. Deteksi box yang terlalu jangkung dibuang karena berisiko merupakan buoy yang salah klasifikasi.
4. Seluruh deteksi berlangsung di kamera atas. Ketika kamera atas mendeteksi `boxblue` seluas minimal 20.000 px², worker mengambil dan menyimpan frame kamera bawah. `boxgreen` dengan ambang sama menyimpan frame kamera atas. Status dan revisinya ditulis ke cold JSON; gambar dilayani lewat HTTP.
5. Kandidat `buoyred` dan `buoygreen` disaring berdasarkan luas, lalu kandidat terbesar dari setiap warna dipakai.
6. Jika dua buoy ada, titik tengah keduanya dibandingkan dengan garis panduan dan dikoreksi oleh PID. Jika hanya satu warna ada, servo memakai offset pencarian tetap. Jika keduanya hilang, PID di-reset dan servo kembali netral.
7. Hasil deteksi, mode buoy, koordinat, rincian PID, PWM, dan live frame diterbitkan melalui `robot_topic`. Area dan koordinat yang tidak lagi terlihat selalu di-reset ke nol.

Nilai inferensi selain ukuran dapat diubah melalui `ASV_YOLO_DEVICE`, `ASV_YOLO_CONFIDENCE`, `ASV_BOX_PHOTO_MIN_AREA`, `ASV_BOX_MAX_HEIGHT_RATIO`, dan `ASV_LIVE_FRAME_JPEG_QUALITY`. Nilai `ASV_YOLO_DEVICE=auto` membiarkan Ultralytics memilih perangkat; bawaan `0` mengikuti konfigurasi GPU dari algoritma tim.

Pemilihan pasangan buoy saat ini masih berdasarkan bbox terbesar per warna, bukan validasi pasangan geometris. Arah fisik `RED_ONLY`/`GREEN_ONLY` juga harus dikonfirmasi saat uji servo karena tanda PWM bergantung pada pemasangan mekanik.

## 6. Jalur dashboard web

1. Dashboard mencoba broker lokal dan subscribe `/local_scope/gui/state`.
2. Koneksi lokal baru dianggap sehat setelah snapshot dengan skema telemetri valid diterima.
3. Jika state lokal tidak diterima atau kedaluwarsa, dashboard memakai `/sistem_broadcast/state_dan_variabel` dari MQTT.
4. Foto tidak dikirim melalui MQTT maupun WebSocket. Dashboard mengambil `/foto/atas.jpg` dan `/foto/bawah.jpg` melalui HTTP ketika revisi foto berubah.
5. Perintah operator dikirim ke `POST /api/command` pada HTTP aktif: lokal memakai `http://IP:8766`, cloud memakai `https://robot.neiaozora.my.id`.
6. Toggle `Disable Local` menutup dan menghentikan reconnect WebSocket telemetri lokal, memakai state MQTT cloud, serta mengarahkan foto dan command ke HTTP robot melalui Cloudflare Tunnel. Pilihan disimpan di browser; protokol foto dan command tetap HTTP, bukan MQTT.
7. `disableInput=true` menjadikan dashboard hanya-pantau. Semua kontrol menampilkan pesan penolakan kecuali `Disable Local`, `Lock Heading`, `Center ASV`, dan `Reset Server History` untuk trajectory.
8. `disableLocal=true` hanya memasang atribut `disabled` pada checkbox. Nilai checked dan pilihan sumber local/cloud tidak diubah oleh variabel tersebut.
9. Peta dapat ditampilkan sampai zoom 22, tetapi OSM hanya diminta sampai native zoom 19. `rotamap.js` memperbesar tile z19 secara lokal pada zoom 20–22 sehingga tidak meminta tile yang tidak tersedia. Google Satellite bersifat opsional melalui `pakaiGoogleSatellite=true`, memakai endpoint tile publik `mt1.google.com` tanpa API key, dan memakai native zoom 20 sebelum diperbesar lokal.
10. Route `/secret` membuka panel “ASV Control Rahasia” tanpa tautan dari dashboard utama. `/secret.html`, source server, dan file lain di luar aset frontend yang diizinkan dikembalikan sebagai 404.

### Aliran arena dan trajectory

1. Tidak ada API atau command untuk mengatur koordinat acuan secara manual.
2. Command misi `start`, `pause`, dan `stop` memperbarui cold state `missionState`. Mode kendaraan `MANUAL`, `AUTO`, status arm, dan `MISSION_CURRENT` tidak menentukan apakah arena berjalan.
3. Pada transisi `missionState=RUNNING`, worker mengambil `titik_mulai` arena aktif, GPS, dan yaw saat itu. Latitude/longitude juga disimpan sebagai `arena.set_dock_sekarang`.
4. `arena.acuan_terkunci=true` mempertahankan acuan yang sama selama sesi. Pause mempertahankan kunci; stop atau reset membuka kunci untuk sesi berikutnya.
5. `VirtualGPSMapper` menghasilkan `arena.posisi_sekarang`, trajectory, serta `arena.visualisasi` yang berisi batas, kotak, buoy merah/hijau, dan docking dalam koordinat GPS siap gambar.
6. Riwayat hanya bertambah ketika `missionState=RUNNING`.
7. JSON `/local_scope/arena/state` membawa arena A/B, arena aktif, status sesi, posisi sekarang, riwayat, visualisasi, acuan, dan galat. GUI-state menggabungkannya ke snapshot frontend/MQTT.
8. Dashboard hanya menggambar data `state.arena`; transformasi koordinat virtual ke GPS dilakukan backend.
9. Satu-satunya command tambahan yang diproses langsung arena worker adalah `clear_history`.
10. Checkbox `Lock Heading` aktif secara default. Saat aktif, bearing peta mengikuti heading kompas sehingga kapal tetap menghadap vertikal dan trajectory, waypoint, serta arena berputar bersama. Saat dimatikan, peta kembali North-up. Fitur ini hanya mengubah tampilan client dan tidak mengubah data MAVLink atau cold state.

API GET internal untuk debugging foto berada pada HTTP robot yang sama:

```text
/api/rahasia?tahan_foto=true
/api/rahasia?tahan_foto=false
/api/rahasia?foto_sekarang=atas
/api/rahasia?foto_sekarang=bawah
/api/rahasia?reset_foto
```

`tahan_foto=true` memblokir foto otomatis dan manual, tetapi tidak memblokir reset. HTTP hanya mengubah cold state dan menerbitkan perintah; akses frame serta penulisan berkas tetap dimiliki vision worker.

## 7. Menjalankan

Runtime target adalah Python 3.8 atau lebih baru. Modul yang memakai anotasi seperti `dict[str, Any]` menunda evaluasi anotasi agar tetap dapat diimpor oleh Python 3.8.

`requirements.txt` mengunci Paho MQTT 2.1.0, websockets 13.1, NumPy 1.24.4, dan dependency utama lain yang masih menyediakan dukungan Python 3.8. Jangan memasang versi `websockets` terbaru tanpa memeriksa batas versi Python.

Periksa sintaks:

```powershell
python main.py --check
```

Di Windows, dependency proyek sudah tersedia di `.venv`. Gunakan:

```powershell
.\.venv\Scripts\python.exe main.py --check
```

`main.py` juga otomatis memilih Python dari `.venv` jika folder tersebut tersedia.

Backend dan GUI:

```powershell
python main.py
```

Backend tanpa jendela GUI:

```powershell
python main.py --tanpa-gui
```

MQTT HiveMQ aktif secara default memakai nilai bawaan `mod01_config.py`. Environment variable `ASV_MQTT_HOST`, `ASV_MQTT_PORT`, `ASV_MQTT_USER`, dan `ASV_MQTT_PASS` hanya dipakai sebagai override; runtime tidak membaca `config.txt`.

Putus internet tidak menghentikan worker MQTT. Paho menunggu dan mencoba koneksi kembali, sedangkan worker lokal lain tetap berjalan. Gunakan `ASV_ENABLE_MQTT=0` atau `--tanpa-mqtt` jika MQTT memang ingin dimatikan.

Bridge MQTT menerima Paho 1.x maupun 2.x agar instalasi Python 3.8 lama di Jetson tidak membuat worker berhenti saat pembuatan client.

```powershell
python main.py
```

Gunakan `python main.py --tanpa-mqtt` hanya ketika sistem memang harus berjalan offline.

HTTP hanya dijalankan satu kali pada `0.0.0.0:8766`. Cloudflare Tunnel meneruskan hostname `robot.neiaozora.my.id` ke `http://127.0.0.1:8766`; jangan menjalankan HTTP worker kedua untuk jalur cloud.

Dashboard web memakai server terpisah pada `0.0.0.0:8767`. Route Cloudflare harus dipisahkan:

```text
robot.neiaozora.my.id     -> http://127.0.0.1:8766
web-robot.neiaozora.my.id -> http://127.0.0.1:8767
```

Dengan pembagian ini, port 8766 hanya melayani API/foto dan port 8767 hanya melayani file frontend.

Semua output anak proses muncul dengan bentuk:

```text
[STDOUT : nama_berkas.py] isi keluaran
```

## 8. Catatan keselamatan firmware

Worker serial saat ini mengikuti `teensy_serial.ino`: paket 6 byte dengan header, PWM, mode, deteksi, dan checksum.

`cek_ino_serial/cek_ino_serial.ino` masih memakai paket 5 byte dan tidak kompatibel. Jangan menguji aktuator sebelum firmware produksi dipilih dan protokol disamakan. Firmware 6 byte juga masih perlu watchdog untuk menetralkan output jika heartbeat komputer berhenti.

## 9. Aturan pengembangan berikutnya

- Jangan membuat state RAM global untuk komunikasi antarproses.
- Jangan menulis hot telemetry ke `state.json`.
- Jangan membuka server WebSocket kedua untuk GUI.
- Jangan menaruh kredensial MQTT di source code.
- Tambahkan topik baru di `mod03_robot_topic.py` dengan namespace `/local_scope/` dan dokumentasikan di sini.
- Jangan menambahkan kembali photo chunk MQTT; foto hasil deteksi dilayani HTTP.
- Jalankan tes dan `python main.py --check` sebelum uji hardware.
