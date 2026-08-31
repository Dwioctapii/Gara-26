extends RefCounted

## Menyusun lintasan lengkap untuk course ASV.
##
## Tanggung jawab file ini hanya geometri dan perencanaan rute. Ia tidak tahu
## tentang keyboard, node UI, atau gerakan kapal per frame. Beberapa kaki course
## memang membutuhkan bentuk khusus: gate awal memakai A*, koridor tengah dibuat
## lurus, dua transisi sempit memakai Bezier, dan ekor course memakai Catmull-Rom.

const Config = preload("res://scripts/core/asv_config.gd")
const GridAStar = preload("res://scripts/planning/grid_astar.gd")


## Memasangkan setiap buoy merah dengan buoy hijau terdekat yang belum dipakai.
## Nilai yang dikembalikan adalah titik tengah gate, dalam urutan buoy merah.
func pair_buoys(
	red_buoys: Array[Vector2],
	green_buoys: Array[Vector2]
) -> Array[Vector2]:
	var gate_centers: Array[Vector2] = []
	var used_green_indices: Array[int] = []

	for red_buoy: Vector2 in red_buoys:
		var nearest_distance := INF
		var nearest_index := -1

		for green_index: int in range(green_buoys.size()):
			if used_green_indices.has(green_index):
				continue

			var distance := red_buoy.distance_to(green_buoys[green_index])
			if distance < nearest_distance:
				nearest_distance = distance
				nearest_index = green_index

		if nearest_index >= 0:
			used_green_indices.append(nearest_index)
			gate_centers.append(
				(red_buoy + green_buoys[nearest_index]) * 0.5
			)

	return gate_centers


## Waypoint misi adalah target bermakna (gate/box), bukan seluruh titik halus
## yang akan diikuti kapal. Route planner mengubah daftar ringkas ini menjadi
## ratusan titik lintasan pada generate_route().
func build_mission_waypoints(
	red_buoys: Array[Vector2],
	green_buoys: Array[Vector2]
) -> Array[Vector2]:
	var result: Array[Vector2] = [Config.RED_BOX]
	result.append_array(pair_buoys(red_buoys, green_buoys))
	result.append(Vector2(Config.BLUE_BOX.x - 1.5, 5.0))
	result.append(Vector2(2.5, Config.GREEN_BOX.y + 1.0))
	result.append(Vector2(10.0, Config.GREEN_BOX.y + 1.0))
	result.append(Config.RED_BOX)
	return result


## Membuat rute dari posisi kapal saat ini menuju waypoint misi yang tersisa.
## first_target_index memungkinkan live replan melanjutkan misi tanpa kembali
## mengejar gate yang sudah dilewati.
func generate_route(
	start_position: Vector2,
	ship_heading: float,
	first_target_index: int,
	mission_waypoints: Array[Vector2],
	red_buoys: Array[Vector2],
	green_buoys: Array[Vector2]
) -> Array[Vector2]:
	if mission_waypoints.size() < 2:
		return []

	var obstacles: Array[Vector2] = []
	obstacles.append_array(red_buoys)
	obstacles.append_array(green_buoys)

	var grid_planner := GridAStar.new(
		Config.MAP_SIZE,
		Config.GRID_RESOLUTION,
		obstacles,
		Config.COURSE_OBSTACLE_MARGIN,
	)

	var segment_start := start_position
	var previous_direction := Vector2.RIGHT.rotated(ship_heading)
	if previous_direction.length_squared() < 0.000001:
		previous_direction = mission_waypoints[1] - segment_start
	if previous_direction.length_squared() < 0.000001:
		previous_direction = Vector2.RIGHT
	previous_direction = previous_direction.normalized()

	var target_start := clampi(
		first_target_index,
		1,
		mission_waypoints.size() - 1,
	)
	var route: Array[Vector2] = []

	for target_index: int in range(target_start, mission_waypoints.size()):
		var goal := mission_waypoints[target_index]
		var segment := _plan_course_leg(
			target_index,
			segment_start,
			goal,
			previous_direction,
			mission_waypoints,
			grid_planner,
			red_buoys,
			green_buoys,
		)

		if not segment.is_empty():
			_append_segment(route, segment)
			segment_start = segment[-1]
			previous_direction = _last_direction(segment, previous_direction)

		# Catmull-Rom telah memasukkan seluruh waypoint ekor sekaligus.
		if target_index >= Config.SMOOTH_TAIL_TARGET:
			break

	return route


func _plan_course_leg(
	target_index: int,
	start: Vector2,
	goal: Vector2,
	incoming_direction: Vector2,
	waypoints: Array[Vector2],
	grid_planner: RefCounted,
	red_buoys: Array[Vector2],
	green_buoys: Array[Vector2]
) -> Array[Vector2]:
	# Gate 3 -> 4 harus melengkung ke atas; garis diagonal memotong course.
	if target_index == Config.BEZIER_GATE_3_TO_4_TARGET:
		return _quadratic_bezier(
			start,
			Vector2(20.0, 20.0),
			goal,
			Config.CURVE_SAMPLE_COUNT,
		)

	# Gate 4 -> 5 -> 6 -> 7 membentuk koridor lurus di tengah pasangan buoy.
	if (
		target_index >= Config.LINEAR_GATE_START_TARGET
		and target_index <= Config.LINEAR_GATE_END_TARGET
	):
		return _interpolate_linear(start, goal, 30)

	# Gate 7 -> 8 memerlukan tangent horizontal saat keluar dan vertikal saat
	# masuk agar badan kapal tidak menyapu buoy di sudut sempit.
	if target_index == Config.SAFE_GATE_8_TARGET:
		return _cubic_bezier(
			start,
			start + Vector2(-2.0, 0.0),
			goal + Vector2(0.0, 1.2),
			goal,
			30,
		)

	# Gate 8 -> 9 meneruskan tangent sebelumnya. Saat live replan dimulai jauh
	# dari pusat gate 8, arah kapal aktual dipakai supaya tidak berputar balik.
	if target_index == Config.SAFE_GATE_9_TARGET:
		var control_1 := start + incoming_direction * 1.2
		if start.distance_to(waypoints[Config.SAFE_GATE_8_TARGET]) < 0.20:
			control_1 = start + Vector2(0.0, -1.2)

		return _cubic_bezier(
			start,
			control_1,
			goal + Vector2(0.0, 1.2),
			goal,
			30,
		)

	# Mulai gate 9 -> 10, satu spline kontinu lebih halus daripada menyambung
	# beberapa kurva terpisah yang dapat menghasilkan perubahan heading mendadak.
	if target_index >= Config.SMOOTH_TAIL_TARGET:
		var tail_controls: Array[Vector2] = [start]
		for tail_index: int in range(target_index, waypoints.size()):
			tail_controls.append(waypoints[tail_index])
		return _catmull_rom(tail_controls, Config.SPLINE_SAMPLE_COUNT)

	var segment: Array[Vector2] = grid_planner.plan(start, goal)
	if segment.is_empty():
		push_warning("A* tidak menemukan rute; memakai garis langsung ke waypoint.")
		return _interpolate_linear(start, goal, 30)

	return _simplify_grid_path(segment, red_buoys, green_buoys)


## Menghapus zig-zag sel A* jika dua titik dapat dihubungkan langsung tanpa
## memasuki margin buoy, lalu mengisi ulang garis agar jarak titik tetap rapat.
func _simplify_grid_path(
	points: Array[Vector2],
	red_buoys: Array[Vector2],
	green_buoys: Array[Vector2]
) -> Array[Vector2]:
	if points.size() < 3:
		return _densify(points)

	var simplified: Array[Vector2] = [points[0]]
	var anchor := 0

	while anchor < points.size() - 1:
		var furthest := anchor + 1
		for candidate: int in range(points.size() - 1, anchor, -1):
			if _segment_is_clear(
				points[anchor],
				points[candidate],
				red_buoys,
				green_buoys,
			):
				furthest = candidate
				break

		simplified.append(points[furthest])
		anchor = furthest

	return _densify(simplified)


func _segment_is_clear(
	start: Vector2,
	goal: Vector2,
	red_buoys: Array[Vector2],
	green_buoys: Array[Vector2]
) -> bool:
	var sample_count := maxi(2, int(ceil(start.distance_to(goal) / 0.18)))
	for sample_index: int in range(sample_count + 1):
		var point := start.lerp(goal, float(sample_index) / float(sample_count))
		for buoy: Vector2 in red_buoys:
			if point.distance_to(buoy) < Config.COURSE_OBSTACLE_MARGIN:
				return false
		for buoy: Vector2 in green_buoys:
			if point.distance_to(buoy) < Config.COURSE_OBSTACLE_MARGIN:
				return false
	return true


func _densify(points: Array[Vector2], spacing: float = 0.35) -> Array[Vector2]:
	if points.is_empty():
		return []

	var result: Array[Vector2] = [points[0]]
	for point_index: int in range(points.size() - 1):
		var distance := points[point_index].distance_to(points[point_index + 1])
		var steps := maxi(1, int(ceil(distance / spacing)))
		for step: int in range(1, steps + 1):
			result.append(points[point_index].lerp(
				points[point_index + 1],
				float(step) / float(steps),
			))
	return result


func _interpolate_linear(
	start: Vector2,
	goal: Vector2,
	sample_count: int
) -> Array[Vector2]:
	if sample_count <= 0:
		return [start, goal]

	var result: Array[Vector2] = []
	for index: int in range(sample_count + 1):
		result.append(start.lerp(goal, float(index) / float(sample_count)))
	return result


func _quadratic_bezier(
	start: Vector2,
	control: Vector2,
	goal: Vector2,
	sample_count: int
) -> Array[Vector2]:
	var result: Array[Vector2] = []
	for index: int in range(sample_count + 1):
		var t := float(index) / float(sample_count)
		var inverse_t := 1.0 - t
		result.append(
			inverse_t * inverse_t * start
			+ 2.0 * inverse_t * t * control
			+ t * t * goal
		)
	return result


func _cubic_bezier(
	start: Vector2,
	control_1: Vector2,
	control_2: Vector2,
	goal: Vector2,
	sample_count: int
) -> Array[Vector2]:
	var result: Array[Vector2] = []
	for index: int in range(sample_count + 1):
		var t := float(index) / float(sample_count)
		var inverse_t := 1.0 - t
		result.append(
			inverse_t ** 3 * start
			+ 3.0 * inverse_t ** 2 * t * control_1
			+ 3.0 * inverse_t * t ** 2 * control_2
			+ t ** 3 * goal
		)
	return result


func _catmull_rom(
	points: Array[Vector2],
	steps_per_segment: int
) -> Array[Vector2]:
	if points.size() < 2:
		return points.duplicate()
	if points.size() == 2:
		return _interpolate_linear(points[0], points[1], steps_per_segment)

	# Ulangi titik ujung agar spline dimulai dan berakhir tepat pada waypoint.
	var extended: Array[Vector2] = [points[0]]
	extended.append_array(points)
	extended.append(points[-1])

	var result: Array[Vector2] = []
	for segment_index: int in range(1, extended.size() - 2):
		var p0 := extended[segment_index - 1]
		var p1 := extended[segment_index]
		var p2 := extended[segment_index + 1]
		var p3 := extended[segment_index + 2]

		for step: int in range(steps_per_segment + 1):
			if segment_index > 1 and step == 0:
				continue

			var t := float(step) / float(steps_per_segment)
			var t_squared := t * t
			var t_cubed := t_squared * t
			result.append(0.5 * (
				2.0 * p1
				+ (-p0 + p2) * t
				+ (2.0 * p0 - 5.0 * p1 + 4.0 * p2 - p3) * t_squared
				+ (-p0 + 3.0 * p1 - 3.0 * p2 + p3) * t_cubed
			))

	return result


func _append_segment(route: Array[Vector2], segment: Array[Vector2]) -> void:
	for point_index: int in range(segment.size()):
		if not route.is_empty() and point_index == 0:
			continue
		route.append(segment[point_index])


func _last_direction(
	segment: Array[Vector2],
	fallback: Vector2
) -> Vector2:
	if segment.size() < 2:
		return fallback

	var direction := segment[-1] - segment[-2]
	return direction.normalized() if direction.length_squared() > 0.000001 else fallback
