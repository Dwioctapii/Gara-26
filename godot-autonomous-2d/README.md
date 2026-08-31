# ASV Autonomous 2D

Simulasi ini memperlihatkan kapal ASV mengikuti course buoy dengan live
replanning. Koordinat dunia memakai meter: **X+ ke Timur** dan **Y+ ke Utara**.

## Struktur kode

```text
scenes/
├── main.tscn                 Komposisi simulasi, input, peta, dan UI
└── ui/status_hud.tscn        Layout panel informasi

scripts/
├── path_planner.gd           Pengatur state dan alur hidup simulasi
├── core/
│   ├── asv_config.gd         Dimensi, posisi course, dan parameter bersama
│   └── mavlink_coordinates.gd Konversi koordinat/yaw ke MAVLink NED
├── input/
│   └── simulation_input.gd   Pemetaan keyboard ke perintah simulasi
├── planning/
│   ├── course_planner.gd     A*, Bezier, spline, dan urutan waypoint
│   └── grid_astar.gd         Pembungkus AStarGrid2D milik Godot
└── ui/
    ├── map_renderer.gd       Gambar grid, buoy, rute, jejak, dan kapal
    └── status_hud.gd         Teks status dan petunjuk kontrol
```

`path_planner.gd` adalah pintu masuk utama, tetapi tidak lagi mengerjakan semua
hal sendiri. Ia menyimpan state kapal dan memanggil modul yang sesuai. UI hanya
membaca snapshot state, sedangkan planner tidak mengetahui node atau ukuran
layar.

## Alur perencanaan

1. Buoy merah dipasangkan dengan buoy hijau terdekat untuk memperoleh pusat
   gate.
2. Pusat gate dan tiga titik pendekatan box disusun menjadi waypoint misi.
3. Kaki awal direncanakan dengan `AStarGrid2D` dan disederhanakan jika garis
   langsung aman dari buoy.
4. Bagian course yang bentuknya tetap memakai garis, kurva Bezier, atau spline
   Catmull-Rom agar kapal tidak memotong gate sempit.
5. Ketika buoy dipindah atau diberi noise, rute dibuat ulang dari posisi dan
   heading kapal saat itu. Gate yang sudah dilewati tidak dikejar kembali.

Kode dynamic gate curve lama sengaja dihapus karena tidak pernah dipanggil oleh
alur `generate_path` yang aktif. HUD sekarang menyebut algoritma yang benar-benar
dipakai: **A* + Bezier + Catmull-Rom**.

## Kontrol

| Tombol | Fungsi |
| --- | --- |
| `W`, `A`, `S`, `D` | Memindahkan buoy terpilih |
| `Left`, `Right` | Memilih nomor gate/buoy |
| `Tab` | Beralih antara memindahkan pasangan dan satu buoy |
| `Q` | Memilih buoy merah atau hijau pada mode satu buoy |
| `Space` | Menambahkan noise acak pada semua buoy |
| `R` | Mengembalikan posisi buoy awal |
| `P` | Pause atau melanjutkan simulasi |

## Integrasi MAVLink

Transport jaringan belum ditangani proyek ini. Tiga fungsi kompatibilitas tetap
tersedia pada `path_planner.gd`:

- `map_to_mavlink_ned()`
- `map_heading_to_mav_yaw()`
- `get_mavlink_yaw_quaternion()`

Implementasi konversinya berada di `core/mavlink_coordinates.gd` agar aturan
koordinat tidak tercampur dengan simulasi visual.
