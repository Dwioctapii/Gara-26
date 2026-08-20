# Catatan integrasi MAVLink

Project membuka listener UDP receive-only pada port `14550`. Tekan `B` agar
`LOCAL_POSITION_NED`, `ATTITUDE`, atau `ATTITUDE_QUATERNION` yang diterima
menggerakkan visual kapal. Tekan `T` untuk kembali ke demo otomatis.

Parser ringan di `mavlink_listener.gd` menerima frame MAVLink v1/v2 dan membaca
pesan yang dibutuhkan untuk visualisasi. Parser ini belum memvalidasi CRC dan
tidak mengirim perintah, melakukan arm, atau mengubah mode autopilot.

## Data yang sudah tersedia

Ambil node `/root/Main/Simulation`, kemudian gunakan:

```gdscript
var ned_position: Vector3 = simulation.map_to_mavlink_ned(simulation.ship_position)
var yaw_ned: float = simulation.map_heading_to_mav_yaw(simulation.ship_heading)
var q_wxyz: PackedFloat32Array = simulation.get_mavlink_yaw_quaternion()
```

`q_wxyz` menggunakan urutan MAVLink `(w, x, y, z)`, bukan urutan constructor
Godot `(x, y, z, w)`.

## Pesan yang relevan

- `LOCAL_POSITION_NED`: posisi aktual N/E/D.
- `ATTITUDE_QUATERNION`: attitude aktual dari autopilot/IMU.
- `SET_POSITION_TARGET_LOCAL_NED`: target posisi, kecepatan, yaw, atau yaw-rate.
- `SET_ATTITUDE_TARGET`: gunakan hanya bila autopilot kapal memang menerima
  attitude setpoint.

Untuk ASV datar, planner cukup menghasilkan posisi 2D dan yaw. Quaternion di
demo ini mengasumsikan roll dan pitch nol. Ketika data IMU nyata dipakai,
simpan attitude aktual secara terpisah dari `ship_heading`, karena
`ship_heading` adalah arah trajectory yang diinginkan.
