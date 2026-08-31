# Menjalankan `run_pt_video.py` di Jetson Orin Nano

Versi Jetson tidak memakai `best.onnx` dan tidak memerlukan
`onnxruntime-directml`. Gunakan salah satu dari:

- `best.pt` melalui PyTorch CUDA untuk validasi awal;
- `best.engine` melalui TensorRT FP16 untuk deployment cepat.

TensorRT engine harus diekspor langsung di Jetson yang akan menjalankannya.
Jangan menyalin `best.engine` hasil build Windows atau Jetson lain.

## 1. Siapkan Jetson

Pasang JetPack yang mendukung Orin Nano, kemudian cek instalasi:

```bash
cat /etc/nv_tegra_release
nvcc --version
python3 -c "import tensorrt; print(tensorrt.__version__)"
```

JetPack memasok CUDA, cuDNN, TensorRT, dan OpenCV. PyTorch harus berupa build
ARM64/CUDA yang cocok dengan versi JetPack. Ikuti matriks/wheel resmi NVIDIA;
jangan memakai wheel CPU acak dari PyPI.

Cara paling sederhana adalah container resmi Ultralytics untuk versi JetPack
yang dipakai. Contoh JetPack 6:

```bash
sudo docker pull ultralytics/ultralytics:latest-jetson-jetpack6
sudo docker run --rm -it --runtime=nvidia --network host \
  --device /dev/video0 --ipc=host \
  -v "$PWD":/workspace/yolo8 -w /workspace/yolo8 \
  ultralytics/ultralytics:latest-jetson-jetpack6 bash
python3 -m pip install websocket-client
```

Jika memakai JetPack 7.2, gunakan instalasi native sampai image publik untuk
kombinasi JetPack/perangkat tersebut dinyatakan tervalidasi.

Untuk instalasi native, pastikan binding OpenCV tersedia:

```bash
sudo apt update
sudo apt install -y python3-pip python3-opencv
```

Setelah `python3 -c "import torch; print(torch.cuda.is_available())"`
menghasilkan `True`, instal dependency aplikasi:

```bash
python3 -m pip install -r requirements-jetson.txt
```

Verifikasi lengkap:

```bash
python3 -c "import torch; print(torch.__version__); print(torch.cuda.is_available()); print(torch.cuda.get_device_name(0))"
```

Jika memakai CSI camera, cek baris `GStreamer: YES`:

```bash
python3 -c "import cv2; print(cv2.getBuildInformation())" | grep GStreamer
```

## 2. Uji model `.pt` di CUDA

Dengan file video:

```bash
python3 run_pt_video.py best.pt rekamanlayar.mp4 \
  --backend cuda --no-show --no-save \
  --ws-url ws://IP-NEO-AUTONOMOUS:8770
```

Dengan USB camera `/dev/video0`:

```bash
python3 run_pt_video.py best.pt 0 \
  --backend cuda --no-show --no-save \
  --ws-url ws://IP-NEO-AUTONOMOUS:8770
```

Untuk CSI camera, berikan pipeline GStreamer dari konfigurasi sensor kamera:

```bash
python3 run_pt_video.py best.pt --backend cuda --no-show --no-save \
  --gstreamer 'nvarguscamerasrc ! video/x-raw(memory:NVMM),width=1280,height=720,framerate=30/1 ! nvvidconv ! video/x-raw,format=BGRx ! videoconvert ! video/x-raw,format=BGR ! appsink drop=1 max-buffers=1' \
  --ws-url ws://IP-NEO-AUTONOMOUS:8770
```

## 3. Export TensorRT pada Jetson

Jalankan sekali. Opsi ini membuat TensorRT FP16 engine dan langsung menguji
video/source yang diberikan:

```bash
python3 run_pt_video.py best.pt rekamanlayar.mp4 \
  --backend cuda --force-export --no-show --no-save
```

Setelah `best.engine` terbentuk, gunakan untuk operasi normal:

```bash
python3 run_pt_video.py best.engine 0 \
  --backend cuda --no-show --no-save \
  --ws-url ws://IP-NEO-AUTONOMOUS:8770
```

Pada Jetson, `--backend auto` juga memilih CUDA secara otomatis. Menuliskan
`--backend cuda` tetap disarankan saat commissioning agar konfigurasi jelas.

## 4. Mode daya dan pemeriksaan performa

Aktifkan mode daya tertinggi yang tersedia untuk perangkat, lalu kunci clock:

```bash
sudo nvpmodel -q
sudo nvpmodel -m 0
sudo jetson_clocks
```

Nomor mode `-m` dapat berbeda menurut image/perangkat; lihat hasil dan panduan
`nvpmodel` sebelum memilihnya. Pantau penggunaan resource dengan `tegrastats`:

```bash
sudo tegrastats
```

Untuk produksi tanpa monitor, selalu gunakan `--no-show`; untuk kamera live,
gunakan juga `--no-save` agar encoding video tidak mengambil resource tambahan.

## Troubleshooting singkat

- `'str' object has no attribute 'names'`: gunakan `cuda_engine.py` terbaru.
  Backend sekarang baru membaca nama kelas setelah inferensi warm-up pertama,
  sehingga kompatibel dengan Ultralytics/TensorRT Jetson versi lama.
- Warning `Using an engine plan file across different models of devices`:
  jangan lanjut memakai engine tersebut. Simpan sebagai backup lalu export
  ulang langsung pada Orin Nano:

  ```bash
  mv best.engine best.engine.perangkat-lama
  python3 run_pt_video.py best.pt 0 \
    --backend cuda --force-export --no-show --no-save
  ```

- Warning/error `np.bool`: backend terbaru menyediakan compatibility alias
  untuk TensorRT lama yang dipakai beberapa versi JetPack.
- `torch.cuda.is_available() = False`: wheel PyTorch tidak cocok dengan
  JetPack atau yang terpasang adalah build CPU.
- `best.engine` gagal dibuka: hapus engine dan ekspor ulang dari `best.pt` pada
  Jetson target.
- USB camera gagal: cek `v4l2-ctl --list-devices` dan izin `/dev/video*`.
- CSI camera gagal: cek apakah OpenCV memiliki GStreamer melalui
  `cv2.getBuildInformation()` dan sesuaikan pipeline dengan resolusi sensor.
- WebSocket tidak terkoneksi: pastikan port target Neo `8770` terbuka dan URL
  memakai IP board yang menjalankan `neo-autonomous`.
