extends RefCounted

## Konversi koordinat planner 2D ke konvensi MAVLink LOCAL_NED.
##
## Planner memakai X=Timur, Y=Utara, dan sudut positif berlawanan arah jarum
## jam. MAVLink NED memakai X=Utara, Y=Timur, Z=Bawah, dan yaw positif searah
## jarum jam. Semua perbedaan konvensi itu diselesaikan di file kecil ini.


static func map_to_local_ned(point: Vector2, height_up: float = 0.0) -> Vector3:
	return Vector3(point.y, point.x, -height_up)


static func heading_to_mav_yaw(map_heading: float) -> float:
	return wrapf(PI * 0.5 - map_heading, -PI, PI)


## MAVLink mengurutkan quaternion sebagai (w, x, y, z). Kapal pada simulasi
## datar, jadi komponen roll dan pitch selalu nol.
static func yaw_quaternion(map_heading: float) -> PackedFloat32Array:
	var yaw_ned := heading_to_mav_yaw(map_heading)
	return PackedFloat32Array([
		cos(yaw_ned * 0.5),
		0.0,
		0.0,
		sin(yaw_ned * 0.5),
	])
