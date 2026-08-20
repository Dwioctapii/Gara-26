extends Node2D

# ============================================================================
# ASV DYNAMIC PATH PLANNER - GODOT 4.5.1
# ============================================================================
#
# FITUR:
# - Dimensi kapal nyata: 1.04 m x 0.52 m
# - Red + Green buoy dipasangkan menjadi gate
# - Dynamic cubic Bezier untuk masuk gate
# - Lookahead berdasarkan:
#       * kecepatan kapal
#       * sudut tikungan
#       * lebar gate
#       * ukuran kapal
# - Collision checking terhadap buoy
# - Jika curve terlalu dekat buoy -> lookahead diperbesar otomatis
# - A* untuk bagian non-gate
# - Live replanning
# - Kapal TIDAK reset ketika buoy berubah
# - Buoy pair dapat digeser bersama
# - Auto-fit map ke window
# - Planned path kuning + traveled trail merah
# - Safe cubic transition gate 7 -> 8 -> 9
# - Helper koordinat/quaternion MAVLink (tanpa transport UDP)
#
# CONTROL:
#
# W/A/S/D       = Geser buoy terpilih
# LEFT/RIGHT    = Pilih gate/buoy pair
# TAB           = PAIR / SINGLE
# Q             = RED / GREEN saat SINGLE
# SPACE         = Tambahkan noise buoy
# R             = Reset buoy
# P             = Pause
#
# WORLD:
# X+ = kanan / timur
# Y+ = atas / utara
#
# ============================================================================


# ============================================================================
# 1. DIMENSI KAPAL NYATA
# ============================================================================

const SHIP_LENGTH: float = 1.04
const SHIP_WIDTH: float = 0.52

# Estimasi radius buoy.
# Ubah kalau ukuran buoy lomba sebenarnya diketahui.
const BUOY_RADIUS: float = 0.15

# Margin tambahan untuk error posisi / kontrol.
const NAVIGATION_MARGIN: float = 0.30

# Radius diagonal kapal untuk collision umum.
const SHIP_COLLISION_RADIUS: float = 0.58

# Collision radius terhadap buoy untuk trajectory umum.
const BUOY_SAFE_RADIUS: float = (
	SHIP_COLLISION_RADIUS
	+ BUOY_RADIUS
	+ NAVIGATION_MARGIN
)

# Saat benar-benar melewati gate, yang penting terutama lebar kapal.
const GATE_REQUIRED_HALF_WIDTH: float = (
	SHIP_WIDTH * 0.5
	+ BUOY_RADIUS
	+ NAVIGATION_MARGIN
)

# Radius praktis saat mengikuti curve gate. Nilai ini tetap lebih besar dari
# half-width kapal + radius buoy (0.41 m), tetapi tidak membuat gate 1.3-1.5 m
# secara matematis mustahil dilalui.
const GATE_CURVE_SAFE_RADIUS: float = (
	SHIP_WIDTH * 0.5
	+ BUOY_RADIUS
	+ 0.18
)


# ============================================================================
# 2. WORLD DATA
# ============================================================================

var red_box: Vector2 = Vector2(20.5, 0.0)
var green_box: Vector2 = Vector2(5.5, 1.0)
var blue_box: Vector2 = Vector2(2.5, 4.0)


# ============================================================================
# 3. DEFAULT BUOY
# ============================================================================

var red_balls_default: Array[Vector2] = [
	Vector2(20.0, 7.0),
	Vector2(18.7, 10.0),
	Vector2(20.5, 12.6),
	Vector2(14.5, 18.5),
	Vector2(12.5, 18.5),
	Vector2(10.5, 18.5),
	Vector2(8.5, 18.5),
	Vector2(1.5, 15.0),
	Vector2(0.0, 11.5),
	Vector2(0.0, 7.5)
]


var green_balls_default: Array[Vector2] = [
	Vector2(21.5, 7.0),
	Vector2(20.2, 10.0),
	Vector2(22.1, 12.6),
	Vector2(14.5, 20.0),
	Vector2(12.5, 20.0),
	Vector2(10.5, 20.0),
	Vector2(8.5, 20.0),
	Vector2(3.0, 15.0),
	Vector2(1.3, 11.5),
	Vector2(1.3, 7.5)
]


var red_balls: Array[Vector2] = []
var green_balls: Array[Vector2] = []

var decorative_green: Array[Vector2] = []


# ============================================================================
# 4. PATH PLANNING PARAMETERS
# ============================================================================

const GRID_RESOLUTION: float = 0.5
const OBSTACLE_MARGIN: float = 1.5
# Margin course aktual. 1.5 m membuat midpoint gate ikut tertutup grid dan
# menyebabkan planner keluar-masuk gate secara berulang.
const COURSE_OBSTACLE_MARGIN: float = 0.58
const MAP_SIZE: float = 35.0

const WAYPOINT_RADIUS: float = 1.0
const PATH_POINT_RADIUS: float = 0.25

const SHIP_SPEED: float = 2.0

const BUOY_MOVE_STEP: float = 0.5


# ============================================================================
# 5. DYNAMIC CORNERING PARAMETERS
# ============================================================================

# Minimum lookahead.
const MIN_GATE_LOOKAHEAD: float = 2.0

# Normal maximum lookahead.
const MAX_GATE_LOOKAHEAD: float = 9.0

# Pengaruh speed.
const LOOKAHEAD_SPEED_GAIN: float = 1.20

# Pengaruh sudut belokan.
const LOOKAHEAD_ANGLE_GAIN: float = 4.0

# Jarak keluar setelah center gate.
const MIN_GATE_EXIT_DISTANCE: float = 1.5
const MAX_GATE_EXIT_DISTANCE: float = 4.0

# Retry jika curve menyentuh unsafe area buoy.
const CURVE_RETRY_STEP: float = 0.75
const CURVE_MAX_ATTEMPTS: int = 10

# Jumlah sample Bézier.
const CURVE_SAMPLE_COUNT: int = 60

# Aturan course khusus yang dipertahankan dari versi final 3D/2D.
const BEZIER_GATE_3_TO_4_TARGET: int = 4
const LINEAR_GATE_START_TARGET: int = 5
const LINEAR_GATE_END_TARGET: int = 7
const SAFE_GATE_8_TARGET: int = 8
const SAFE_GATE_9_TARGET: int = 9
const SMOOTH_TAIL_TARGET: int = 10
const SPLINE_SAMPLE_COUNT: int = 20
const TRAIL_RECORD_DISTANCE: float = 0.12


# ============================================================================
# 6. VISUAL PARAMETERS
# ============================================================================

const HUD_WIDTH: float = 350.0
const VIEW_PADDING: float = 35.0
const WORLD_PADDING_METERS: float = 1.5

const MIN_DRAW_SCALE: float = 3.0
const MAX_DRAW_SCALE: float = 40.0

var draw_scale: float = 10.0
var draw_offset: Vector2 = Vector2.ZERO

var view_min: Vector2 = Vector2.ZERO
var view_max: Vector2 = Vector2(MAP_SIZE, MAP_SIZE)


# ============================================================================
# 7. SHIP SIMULATION
# ============================================================================

var ship_position: Vector2 = Vector2.ZERO
var ship_heading: float = 0.0

var current_path: Array[Vector2] = []
var mission_waypoints: Array[Vector2] = []
var traveled_path: Array[Vector2] = []
var last_trail_position: Vector2 = Vector2(INF, INF)

var current_path_index: int = 0
var current_wp_index: int = 0

var is_paused: bool = false
var mission_complete: bool = false


# ============================================================================
# 8. BUOY SELECTION
# ============================================================================

var selected_index: int = 0

# 0 = RED
# 1 = GREEN
var selected_buoy_type: int = 0

# true = red + green bergerak bersama.
var move_buoy_pair: bool = true


# ============================================================================
# 9. SIGNALS
# ============================================================================

signal path_updated(new_path)
signal waypoint_reached(index, waypoint)
signal mission_finished()


# ============================================================================
# 10. READY
# ============================================================================

func _ready() -> void:

	randomize()

	red_balls = red_balls_default.duplicate(true)
	green_balls = green_balls_default.duplicate(true)

	decorative_green = [
		red_box + Vector2(-0.7, 1.0),
		red_box + Vector2(0.0, 1.0),
		red_box + Vector2(0.7, 1.0)
	]

	ship_position = red_box

	generate_path(true)

	if not current_path.is_empty():
		ship_position = current_path[0]

	traveled_path.clear()
	last_trail_position = Vector2(INF, INF)
	record_traveled_point(true)

	queue_redraw()


# ============================================================================
# 11. PAIR BUOYS
# ============================================================================

func pair_buoys(
	reds: Array[Vector2],
	greens: Array[Vector2]
) -> Array[Vector2]:

	var pairs: Array[Vector2] = []
	var used_green: Array[int] = []

	for red: Vector2 in reds:

		var best_distance: float = INF
		var best_index: int = -1

		for i: int in range(greens.size()):

			if used_green.has(i):
				continue

			var distance: float = red.distance_to(greens[i])

			if distance < best_distance:

				best_distance = distance
				best_index = i

		if best_index != -1:

			used_green.append(best_index)

			pairs.append(
				(red + greens[best_index]) * 0.5
			)

	return pairs


# ============================================================================
# 12. LINEAR
# ============================================================================

func interpolate_linear(
	p1: Vector2,
	p2: Vector2,
	num_points: int = 20
) -> Array[Vector2]:

	var result: Array[Vector2] = []

	if num_points <= 0:

		result.append(p1)
		result.append(p2)

		return result

	for i: int in range(num_points + 1):

		var t: float = float(i) / float(num_points)

		result.append(
			p1.lerp(p2, t)
		)

	return result


# ============================================================================
# 13. CUBIC BEZIER
# ============================================================================

func bezier_cubic(
	p0: Vector2,
	p1: Vector2,
	p2: Vector2,
	p3: Vector2,
	num_points: int = CURVE_SAMPLE_COUNT
) -> Array[Vector2]:

	var result: Array[Vector2] = []

	if num_points <= 0:

		result.append(p0)
		result.append(p3)

		return result

	for i: int in range(num_points + 1):

		var t: float = float(i) / float(num_points)
		var u: float = 1.0 - t

		var point: Vector2 = (
			u * u * u * p0
			+
			3.0 * u * u * t * p1
			+
			3.0 * u * t * t * p2
			+
			t * t * t * p3
		)

		result.append(point)

	return result


# ============================================================================
# 13A. QUADRATIC BEZIER KHUSUS COURSE
# ============================================================================

func bezier_quadratic_course(
	start: Vector2,
	control: Vector2,
	goal: Vector2,
	num_points: int = CURVE_SAMPLE_COUNT
) -> Array[Vector2]:

	var result: Array[Vector2] = []

	for i: int in range(num_points + 1):

		var t: float = float(i) / float(num_points)
		var inverse_t: float = 1.0 - t

		result.append(
			inverse_t * inverse_t * start
			+
			2.0 * inverse_t * t * control
			+
			t * t * goal
		)

	return result


# ============================================================================
# 13B. CATMULL-ROM KHUSUS SMOOTH TAIL
# ============================================================================

func catmull_rom_course(
	points: Array[Vector2],
	steps_per_segment: int = SPLINE_SAMPLE_COUNT
) -> Array[Vector2]:

	if points.size() < 2:
		return points.duplicate()

	if points.size() == 2:
		return interpolate_linear(
			points[0],
			points[1],
			steps_per_segment
		)

	var extended: Array[Vector2] = [points[0]]
	extended.append_array(points)
	extended.append(points[points.size() - 1])

	var result: Array[Vector2] = []

	for segment_index: int in range(1, extended.size() - 2):

		var p0: Vector2 = extended[segment_index - 1]
		var p1: Vector2 = extended[segment_index]
		var p2: Vector2 = extended[segment_index + 1]
		var p3: Vector2 = extended[segment_index + 2]

		for step: int in range(steps_per_segment + 1):

			if segment_index > 1 and step == 0:
				continue

			var t: float = float(step) / float(steps_per_segment)
			var t2: float = t * t
			var t3: float = t2 * t

			result.append(
				0.5
				*
				(
					2.0 * p1
					+
					(-p0 + p2) * t
					+
					(
						2.0 * p0
						- 5.0 * p1
						+ 4.0 * p2
						- p3
					) * t2
					+
					(
						-p0
						+ 3.0 * p1
						- 3.0 * p2
						+ p3
					) * t3
				)
			)

	return result


# ============================================================================
# 13C. SAFE PER-LEG A* SIMPLIFICATION
# ============================================================================

func course_segment_is_clear(
	start: Vector2,
	goal: Vector2
) -> bool:

	var distance: float = start.distance_to(goal)
	var sample_count: int = maxi(
		2,
		int(ceil(distance / 0.18))
	)

	for sample_index: int in range(sample_count + 1):

		var point: Vector2 = start.lerp(
			goal,
			float(sample_index) / float(sample_count)
		)

		for buoy: Vector2 in red_balls:

			if point.distance_to(buoy) < COURSE_OBSTACLE_MARGIN:
				return false

		for buoy: Vector2 in green_balls:

			if point.distance_to(buoy) < COURSE_OBSTACLE_MARGIN:
				return false

	return true


func densify_course_segment(
	points: Array[Vector2],
	spacing: float = 0.35
) -> Array[Vector2]:

	var result: Array[Vector2] = []

	if points.is_empty():
		return result

	result.append(points[0])

	for i: int in range(points.size() - 1):

		var distance: float = points[i].distance_to(points[i + 1])
		var steps: int = maxi(1, int(ceil(distance / spacing)))

		for step: int in range(1, steps + 1):

			result.append(
				points[i].lerp(
					points[i + 1],
					float(step) / float(steps)
				)
			)

	return result


func simplify_course_segment(
	points: Array[Vector2]
) -> Array[Vector2]:

	if points.size() < 3:
		return densify_course_segment(points)

	var simplified: Array[Vector2] = [points[0]]
	var anchor: int = 0

	while anchor < points.size() - 1:

		var furthest: int = anchor + 1

		for candidate: int in range(
			points.size() - 1,
			anchor,
			-1
		):

			if course_segment_is_clear(
				points[anchor],
				points[candidate]
			):

				furthest = candidate
				break

		simplified.append(points[furthest])
		anchor = furthest

	return densify_course_segment(simplified)


# ============================================================================
# 14. CALCULATE GATE FORWARD
# ============================================================================

func calculate_gate_forward(
	red_buoy: Vector2,
	green_buoy: Vector2,
	approach_position: Vector2
) -> Vector2:

	var gate_axis: Vector2 = (
		green_buoy - red_buoy
	)

	if gate_axis.length_squared() < 0.000001:
		return Vector2.RIGHT

	gate_axis = gate_axis.normalized()

	# Tegak lurus terhadap garis red-green.
	var gate_forward: Vector2 = Vector2(
		-gate_axis.y,
		gate_axis.x
	)

	var gate_center: Vector2 = (
		red_buoy + green_buoy
	) * 0.5

	var toward_gate: Vector2 = (
		gate_center - approach_position
	)

	if toward_gate.length_squared() > 0.000001:

		toward_gate = toward_gate.normalized()

		if gate_forward.dot(toward_gate) < 0.0:
			gate_forward = -gate_forward

	return gate_forward


# ============================================================================
# 15. DYNAMIC LOOKAHEAD
# ============================================================================

func calculate_gate_lookahead(
	incoming_direction: Vector2,
	gate_forward: Vector2,
	speed: float,
	gate_width: float
) -> float:

	var incoming: Vector2 = incoming_direction

	if incoming.length_squared() < 0.000001:
		incoming = gate_forward

	incoming = incoming.normalized()

	var forward: Vector2 = gate_forward.normalized()

	var turn_angle: float = abs(
		incoming.angle_to(forward)
	)

	var normalized_angle: float = (
		turn_angle / PI
	)

	var speed_component: float = (
		maxf(speed, 0.0)
		*
		LOOKAHEAD_SPEED_GAIN
	)

	var angle_component: float = (
		normalized_angle
		*
		LOOKAHEAD_ANGLE_GAIN
	)

	# ------------------------------------------------------------------------
	# CLEARANCE BERDASARKAN LEBAR KAPAL
	# ------------------------------------------------------------------------

	var gate_half_width: float = gate_width * 0.5

	var clearance: float = (
		gate_half_width
		-
		GATE_REQUIRED_HALF_WIDTH
	)

	var clearance_component: float = 0.0

	if clearance < 1.0:

		clearance_component = (
			clampf(
				1.0 - clearance,
				0.0,
				2.5
			)
			*
			2.5
		)

	var lookahead: float = (
		MIN_GATE_LOOKAHEAD
		+
		speed_component
		+
		angle_component
		+
		clearance_component
	)

	return clampf(
		lookahead,
		MIN_GATE_LOOKAHEAD,
		MAX_GATE_LOOKAHEAD
	)


# ============================================================================
# 16. EXIT DISTANCE
# ============================================================================

func calculate_gate_exit_distance(
	gate_width: float,
	turn_angle: float
) -> float:

	var angle_factor: float = (
		abs(turn_angle) / PI
	)

	var width_factor: float = 0.0

	if gate_width < 4.0:

		width_factor = (
			4.0 - gate_width
		) * 0.5

	var distance: float = (
		MIN_GATE_EXIT_DISTANCE
		+
		angle_factor * 1.5
		+
		width_factor
	)

	return clampf(
		distance,
		MIN_GATE_EXIT_DISTANCE,
		MAX_GATE_EXIT_DISTANCE
	)


# ============================================================================
# 17. CURVE SAFETY
# ============================================================================

func curve_is_safe_against_all_buoys(
	curve: Array[Vector2],
	target_red: Vector2,
	target_green: Vector2
) -> bool:

	if curve.is_empty():
		return false

	# Jangan periksa bagian sangat awal.
	# Start bisa masih dekat buoy sebelumnya.
	var start_index: int = int(
		float(curve.size()) * 0.08
	)

	for point_index: int in range(
		start_index,
		curve.size()
	):

		var point: Vector2 = curve[point_index]

		# ------------------------------------------------------------
		# TARGET GATE
		# ------------------------------------------------------------

		if point.distance_to(target_red) < GATE_CURVE_SAFE_RADIUS:
			return false

		if point.distance_to(target_green) < GATE_CURVE_SAFE_RADIUS:
			return false

		# ------------------------------------------------------------
		# ALL RED
		# ------------------------------------------------------------

		for buoy: Vector2 in red_balls:

			# Target gate sudah diperiksa.
			if buoy.is_equal_approx(target_red):
				continue

			# Live/repeated gate curves may start inside the safe radius of the
			# previous gate. Allow only the departure portion for that buoy.
			if (
				curve[0].distance_to(buoy) < GATE_CURVE_SAFE_RADIUS
				and
				point_index < int(float(curve.size()) * 0.35)
			):
				continue

			if point.distance_to(buoy) < GATE_CURVE_SAFE_RADIUS:
				return false

		# ------------------------------------------------------------
		# ALL GREEN
		# ------------------------------------------------------------

		for buoy: Vector2 in green_balls:

			if buoy.is_equal_approx(target_green):
				continue

			if (
				curve[0].distance_to(buoy) < GATE_CURVE_SAFE_RADIUS
				and
				point_index < int(float(curve.size()) * 0.35)
			):
				continue

			if point.distance_to(buoy) < GATE_CURVE_SAFE_RADIUS:
				return false

	return true


# ============================================================================
# 18. CREATE DYNAMIC GATE CURVE
# ============================================================================

func create_dynamic_gate_curve(
	start: Vector2,
	incoming_direction: Vector2,
	red_buoy: Vector2,
	green_buoy: Vector2,
	speed: float
) -> Array[Vector2]:

	var gate_center: Vector2 = (
		red_buoy + green_buoy
	) * 0.5

	var gate_width: float = (
		red_buoy.distance_to(green_buoy)
	)

	if gate_width < 0.1:

		push_warning(
			"Gate terlalu sempit atau kedua buoy hampir berada di posisi sama."
		)

		return interpolate_linear(
			start,
			gate_center,
			30
		)

	var gate_forward: Vector2 = (
		calculate_gate_forward(
			red_buoy,
			green_buoy,
			start
		)
	)

	var incoming: Vector2 = incoming_direction

	if incoming.length_squared() < 0.000001:

		incoming = (
			gate_center - start
		)

	if incoming.length_squared() < 0.000001:
		incoming = gate_forward

	incoming = incoming.normalized()

	var turn_angle: float = abs(
		incoming.angle_to(
			gate_forward
		)
	)

	var base_lookahead: float = (
		calculate_gate_lookahead(
			incoming,
			gate_forward,
			speed,
			gate_width
		)
	)

	var exit_distance: float = (
		calculate_gate_exit_distance(
			gate_width,
			turn_angle
		)
	)

	# Target berada setelah center gate.
	var target: Vector2 = (
		gate_center
		+
		gate_forward * exit_distance
	)

	var fallback_curve: Array[Vector2] = []

	for attempt: int in range(
		CURVE_MAX_ATTEMPTS
	):

		var lookahead: float = (
			base_lookahead
			+
			float(attempt)
			*
			CURVE_RETRY_STEP
		)

		lookahead = minf(
			lookahead,
			MAX_GATE_LOOKAHEAD + 4.0
		)

		# ------------------------------------------------------------
		# CONTROL 1
		#
		# Menjaga kurva keluar dari start mengikuti heading masuk.
		# ------------------------------------------------------------

		var control_1: Vector2 = (
			start
			+
			incoming * lookahead
		)

		# ------------------------------------------------------------
		# CONTROL 2
		#
		# Menjaga heading menjelang exit menjadi sejajar gate.
		# ------------------------------------------------------------

		var control_2: Vector2 = (
			target
			-
			gate_forward * lookahead
		)

		var candidate: Array[Vector2] = (
			bezier_cubic(
				start,
				control_1,
				control_2,
				target,
				CURVE_SAMPLE_COUNT
			)
		)

		fallback_curve = candidate

		if curve_is_safe_against_all_buoys(
			candidate,
			red_buoy,
			green_buoy
		):
			return candidate

	push_warning(
		"Dynamic Bezier tidak menemukan curve yang sepenuhnya aman. Memakai attempt terakhir."
	)

	return fallback_curve


# ============================================================================
# 19. A* PLANNER
# ============================================================================

class AStarPlanner:

	var grid_size: int
	var resolution: float
	var margin: float

	var obstacles: Array[Vector2]
	var grid: Array


	func _init(
		map_size: float,
		p_resolution: float,
		p_obstacles: Array[Vector2],
		p_margin: float
	) -> void:

		resolution = p_resolution
		margin = p_margin
		obstacles = p_obstacles

		grid_size = int(
			ceil(
				map_size / resolution
			)
		)

		grid = _create_grid()


	func _create_grid() -> Array:

		var result: Array = []

		for y: int in range(grid_size):

			var row: Array[int] = []

			for x: int in range(grid_size):
				row.append(0)

			result.append(row)

		var margin_cells: int = int(
			ceil(
				margin / resolution
			)
		)

		for obstacle: Vector2 in obstacles:

			var gx: int = int(
				floor(
					obstacle.x / resolution
				)
			)

			var gy: int = int(
				floor(
					obstacle.y / resolution
				)
			)

			for dx: int in range(
				-margin_cells,
				margin_cells + 1
			):

				for dy: int in range(
					-margin_cells,
					margin_cells + 1
				):

					var distance: float = sqrt(
						float(
							dx * dx
							+
							dy * dy
						)
					)

					if distance > float(margin_cells):
						continue

					var nx: int = gx + dx
					var ny: int = gy + dy

					if (
						nx >= 0
						and nx < grid_size
						and ny >= 0
						and ny < grid_size
					):

						result[ny][nx] = 1

		return result


	func _world_to_grid(
		position: Vector2
	) -> Vector2i:

		return Vector2i(
			int(
				floor(
					position.x / resolution
				)
			),

			int(
				floor(
					position.y / resolution
				)
			)
		)


	func _grid_to_world(
		position: Vector2i
	) -> Vector2:

		return Vector2(
			position.x * resolution
			+
			resolution * 0.5,

			position.y * resolution
			+
			resolution * 0.5
		)


	func _is_valid(
		position: Vector2i
	) -> bool:

		if position.x < 0:
			return false

		if position.y < 0:
			return false

		if position.x >= grid_size:
			return false

		if position.y >= grid_size:
			return false

		return grid[position.y][position.x] == 0


	func _get_neighbors(
		position: Vector2i
	) -> Array:

		var result: Array = []

		for dx: int in [-1, 0, 1]:

			for dy: int in [-1, 0, 1]:

				if dx == 0 and dy == 0:
					continue

				var neighbor: Vector2i = Vector2i(
					position.x + dx,
					position.y + dy
				)

				if not _is_valid(neighbor):
					continue

				var cost: float = 1.0

				if dx != 0 and dy != 0:
					cost = 1.41421356237

				result.append([
					neighbor,
					cost
				])

		return result


	func _heuristic(
		a: Vector2i,
		b: Vector2i
	) -> float:

		var dx: float = float(a.x - b.x)
		var dy: float = float(a.y - b.y)

		return sqrt(
			dx * dx + dy * dy
		)


	func _compare_open_set(
		a: Array,
		b: Array
	) -> bool:

		if float(a[0]) == float(b[0]):

			return int(a[1]) < int(b[1])

		return float(a[0]) < float(b[0])


	func _find_nearest_valid_cell(
		start: Vector2i
	) -> Vector2i:

		if _is_valid(start):
			return start

		for radius: int in range(1, 15):

			for dx: int in range(
				-radius,
				radius + 1
			):

				for dy: int in range(
					-radius,
					radius + 1
				):

					var candidate: Vector2i = Vector2i(
						start.x + dx,
						start.y + dy
					)

					if _is_valid(candidate):
						return candidate

		return start


	func plan(
		start: Vector2,
		goal: Vector2
	) -> Array[Vector2]:

		var start_grid: Vector2i = (
			_world_to_grid(start)
		)

		var goal_grid: Vector2i = (
			_world_to_grid(goal)
		)

		start_grid = (
			_find_nearest_valid_cell(
				start_grid
			)
		)

		goal_grid = (
			_find_nearest_valid_cell(
				goal_grid
			)
		)

		if not _is_valid(start_grid):
			return []

		if not _is_valid(goal_grid):
			return []

		var open_set: Array = []
		var came_from: Dictionary = {}
		var g_cost: Dictionary = {}

		var counter: int = 0

		open_set.append([
			_heuristic(
				start_grid,
				goal_grid
			),
			counter,
			start_grid
		])

		g_cost[start_grid] = 0.0

		counter += 1

		while not open_set.is_empty():

			open_set.sort_custom(
				Callable(
					self,
					"_compare_open_set"
				)
			)

			var current_data: Array = (
				open_set.pop_front()
			)

			var current: Vector2i = (
				current_data[2]
			)

			if current == goal_grid:

				var path: Array[Vector2] = []

				var cursor: Vector2i = current

				while came_from.has(cursor):

					path.append(
						_grid_to_world(
							cursor
						)
					)

					cursor = came_from[cursor]

				path.append(start)

				path.reverse()

				if (
					path.is_empty()
					or
					path[
						path.size() - 1
					].distance_to(goal) > 0.01
				):

					path.append(goal)

				return path

			for neighbor_data: Array in (
				_get_neighbors(current)
			):

				var neighbor: Vector2i = (
					neighbor_data[0]
				)

				var step_cost: float = float(
					neighbor_data[1]
				)

				var current_cost: float = float(
					g_cost[current]
				)

				var tentative_cost: float = (
					current_cost
					+
					step_cost
				)

				if (
					not g_cost.has(neighbor)
					or
					tentative_cost
					<
					float(g_cost[neighbor])
				):

					came_from[neighbor] = current

					g_cost[neighbor] = (
						tentative_cost
					)

					var f_cost: float = (
						tentative_cost
						+
						_heuristic(
							neighbor,
							goal_grid
						)
					)

					open_set.append([
						f_cost,
						counter,
						neighbor
					])

					counter += 1

		return []


# ============================================================================
# 20. BUILD MISSION WAYPOINTS
# ============================================================================

func build_mission_waypoints() -> Array[Vector2]:

	var gates: Array[Vector2] = (
		pair_buoys(
			red_balls,
			green_balls
		)
	)

	var blue_approach: Vector2 = Vector2(
		blue_box.x - 1.5,
		5.0
	)

	var wp13: Vector2 = Vector2(
		2.5,
		green_box.y + 1.0
	)

	var green_approach: Vector2 = Vector2(
		10.0,
		green_box.y + 1.0
	)

	var result: Array[Vector2] = []

	result.append(red_box)

	for gate: Vector2 in gates:
		result.append(gate)

	result.append(blue_approach)
	result.append(wp13)
	result.append(green_approach)
	result.append(red_box)

	return result


# ============================================================================
# 21. GENERATE PATH
# ============================================================================

func generate_path(
	reset_mission: bool = true
) -> void:

	mission_waypoints = (
		build_mission_waypoints()
	)

	var obstacles: Array[Vector2] = []

	for buoy: Vector2 in red_balls:
		obstacles.append(buoy)

	for buoy: Vector2 in green_balls:
		obstacles.append(buoy)

	var planner := AStarPlanner.new(
		MAP_SIZE,
		GRID_RESOLUTION,
		obstacles,
		COURSE_OBSTACLE_MARGIN
	)

	var raw_segments: Array = []

	if mission_waypoints.size() < 2:

		current_path = []
		queue_redraw()
		return

	# ------------------------------------------------------------------------
	# START
	# ------------------------------------------------------------------------

	var segment_start: Vector2

	if reset_mission:
		segment_start = mission_waypoints[0]
	else:
		segment_start = ship_position

	var previous_direction: Vector2 = (
		Vector2.RIGHT.rotated(
			ship_heading
		)
	)

	if previous_direction.length_squared() < 0.000001:

		previous_direction = (
			mission_waypoints[1]
			-
			segment_start
		)

	if previous_direction.length_squared() < 0.000001:
		previous_direction = Vector2.RIGHT

	previous_direction = previous_direction.normalized()

	# ------------------------------------------------------------------------
	# START TARGET
	#
	# Kalau live replan, jangan kembali mengejar gate lama.
	# ------------------------------------------------------------------------

	var first_target_index: int = 1

	if not reset_mission:

		first_target_index = clampi(
			current_wp_index,
			1,
			mission_waypoints.size() - 1
		)

	# ------------------------------------------------------------------------
	# BUILD SEGMENTS
	# ------------------------------------------------------------------------

	for target_wp_index: int in range(
		first_target_index,
		mission_waypoints.size()
	):

		var goal: Vector2 = (
			mission_waypoints[
				target_wp_index
			]
		)

		var segment: Array[Vector2] = []

		# ====================================================================
		# COURSE-SPECIFIC ROUTING
		# ====================================================================

		# Gate 3 -> 4: quadratic Bezier asli, jangan diratakan menjadi diagonal.
		if target_wp_index == BEZIER_GATE_3_TO_4_TARGET:

			segment = bezier_quadratic_course(
				segment_start,
				Vector2(20.0, 20.0),
				goal,
				CURVE_SAMPLE_COUNT
			)

		# Gate 4 -> 5 -> 6 -> 7: corridor lurus di tengah pasangan buoy.
		elif (
			target_wp_index >= LINEAR_GATE_START_TARGET
			and
			target_wp_index <= LINEAR_GATE_END_TARGET
		):

			segment = interpolate_linear(
				segment_start,
				goal,
				30
			)

		# Gate 7 -> 8: cubic masuk gate dengan tangent vertikal.
		elif target_wp_index == SAFE_GATE_8_TARGET:

			segment = bezier_cubic(
				segment_start,
				segment_start + Vector2(-2.0, 0.0),
				goal + Vector2(0.0, 1.2),
				goal,
				30
			)

		# Gate 8 -> 9: tangent masuk/keluar sama, clearance minimum 0.65 m.
		elif target_wp_index == SAFE_GATE_9_TARGET:

			var safe_control_1: Vector2

			if segment_start.distance_to(
				mission_waypoints[SAFE_GATE_8_TARGET]
			) < 0.20:

				safe_control_1 = (
					segment_start
					+
					Vector2(0.0, -1.2)
				)

			else:

				safe_control_1 = (
					segment_start
					+
					previous_direction * 1.2
				)

			segment = bezier_cubic(
				segment_start,
				safe_control_1,
				goal + Vector2(0.0, 1.2),
				goal,
				30
			)

		# Mulai gate 9 -> 10 dan seluruh bagian akhir: spline kontinu.
		elif target_wp_index >= SMOOTH_TAIL_TARGET:

			var tail_controls: Array[Vector2] = [segment_start]

			for tail_index: int in range(
				target_wp_index,
				mission_waypoints.size()
			):

				tail_controls.append(
					mission_waypoints[tail_index]
				)

			segment = catmull_rom_course(
				tail_controls,
				SPLINE_SAMPLE_COUNT
			)

		# Gate awal dan waypoint umum memakai A*. Dynamic exit curve lama tidak
		# dipakai karena targetnya berada setelah gate dan membuat loop balik.
		else:

			segment = planner.plan(
				segment_start,
				goal
			)

			if segment.is_empty():

				segment = interpolate_linear(
					segment_start,
					goal,
					30
				)

			else:

				segment = simplify_course_segment(segment)

		# ====================================================================
		# STORE
		# ====================================================================

		if not segment.is_empty():

			raw_segments.append(segment)

			segment_start = (
				segment[
					segment.size() - 1
				]
			)

			if segment.size() >= 2:

				previous_direction = (
					segment[
						segment.size() - 1
					]
					-
					segment[
						segment.size() - 2
					]
				)

				if previous_direction.length_squared() > 0.000001:
					previous_direction = previous_direction.normalized()

		if target_wp_index >= SMOOTH_TAIL_TARGET:
			break

	# ------------------------------------------------------------------------
	# COMBINE
	# ------------------------------------------------------------------------

	var final_path: Array[Vector2] = []

	for segment_index: int in range(
		raw_segments.size()
	):

		var segment: Array = (
			raw_segments[
				segment_index
			]
		)

		for point_index: int in range(
			segment.size()
		):

			if (
				segment_index > 0
				and
				point_index == 0
			):
				continue

			final_path.append(
				segment[point_index] as Vector2
			)

	current_path = final_path

	if reset_mission:

		current_path_index = 0
		current_wp_index = 0
		mission_complete = false

	else:

		current_path_index = 0
		mission_complete = false

	path_updated.emit(current_path)

	queue_redraw()


# ============================================================================
# 22. FIND NEXT WAYPOINT
# ============================================================================

func find_next_mission_waypoint(
	position: Vector2
) -> int:

	if mission_waypoints.is_empty():
		return 0

	var start_index: int = clampi(
		current_wp_index,
		0,
		mission_waypoints.size() - 1
	)

	for i: int in range(
		start_index,
		mission_waypoints.size()
	):

		if (
			position.distance_to(
				mission_waypoints[i]
			)
			>
			WAYPOINT_RADIUS
		):
			return i

	return mission_waypoints.size()


# ============================================================================
# 23. LIVE REPLAN
# ============================================================================

func replan_from_current_position() -> void:

	var saved_position: Vector2 = ship_position
	var saved_heading: float = ship_heading
	var saved_pause: bool = is_paused

	var old_wp_index: int = current_wp_index

	generate_path(false)

	ship_position = saved_position
	ship_heading = saved_heading
	is_paused = saved_pause

	current_path_index = 0

	current_wp_index = max(
		old_wp_index,
		find_next_mission_waypoint(
			ship_position
		)
	)

	mission_complete = false

	queue_redraw()


# ============================================================================
# 24. MOVE BUOY
# ============================================================================

func move_selected_buoy(
	delta_position: Vector2
) -> void:

	if move_buoy_pair:

		if (
			selected_index >= 0
			and
			selected_index < red_balls.size()
			and
			selected_index < green_balls.size()
		):

			red_balls[selected_index] += delta_position
			green_balls[selected_index] += delta_position

	else:

		if selected_buoy_type == 0:

			if (
				selected_index >= 0
				and
				selected_index < red_balls.size()
			):

				red_balls[selected_index] += delta_position

		else:

			if (
				selected_index >= 0
				and
				selected_index < green_balls.size()
			):

				green_balls[selected_index] += delta_position

	replan_from_current_position()


# ============================================================================
# 25. SHIP PHYSICS
# ============================================================================

func _physics_process(
	delta: float
) -> void:

	if is_paused:
		return

	if mission_complete:
		return

	if current_path.is_empty():
		return

	if current_path_index >= current_path.size():

		mission_complete = true

		mission_finished.emit()

		queue_redraw()

		return

	var target: Vector2 = (
		current_path[
			current_path_index
		]
	)

	var difference: Vector2 = (
		target - ship_position
	)

	var distance: float = (
		difference.length()
	)

	if distance <= PATH_POINT_RADIUS:

		current_path_index += 1

		queue_redraw()

		return

	var direction: Vector2 = (
		difference.normalized()
	)

	var travel_distance: float = (
		SHIP_SPEED
		*
		delta
	)

	travel_distance = minf(
		travel_distance,
		distance
	)

	ship_position += (
		direction
		*
		travel_distance
	)

	ship_heading = (
		direction.angle()
	)

	record_traveled_point()

	# ------------------------------------------------------------------------
	# CHECK MISSION WAYPOINT
	# ------------------------------------------------------------------------

	if (
		current_wp_index
		<
		mission_waypoints.size()
	):

		var waypoint: Vector2 = (
			mission_waypoints[
				current_wp_index
			]
		)

		if (
			ship_position.distance_to(
				waypoint
			)
			<=
			WAYPOINT_RADIUS
		):

			waypoint_reached.emit(
				current_wp_index,
				waypoint
			)

			current_wp_index += 1

	queue_redraw()


# ============================================================================
# 25A. RECORD TRAVELED TRAIL
# ============================================================================

func record_traveled_point(
	force: bool = false
) -> void:

	if (
		force
		or
		last_trail_position.x == INF
		or
		ship_position.distance_to(
			last_trail_position
		) >= TRAIL_RECORD_DISTANCE
	):

		traveled_path.append(ship_position)
		last_trail_position = ship_position


# ============================================================================
# 25B. MAVLINK CONVERSION HELPERS
# ============================================================================

# Planner Vector2(East, North) -> MAVLink LOCAL_NED(North, East, Down).
func map_to_mavlink_ned(
	point: Vector2,
	height_up: float = 0.0
) -> Vector3:

	return Vector3(
		point.y,
		point.x,
		-height_up
	)


# Heading planner: nol di Timur, CCW positif.
# Yaw MAVLink NED: nol di Utara, clockwise positif.
func map_heading_to_mav_yaw(
	map_heading: float
) -> float:

	return wrapf(
		PI * 0.5 - map_heading,
		-PI,
		PI
	)


# Urutan MAVLink adalah (w, x, y, z). Kapal datar: roll = pitch = 0.
func get_mavlink_yaw_quaternion() -> PackedFloat32Array:

	var yaw_ned: float = (
		map_heading_to_mav_yaw(
			ship_heading
		)
	)

	return PackedFloat32Array([
		cos(yaw_ned * 0.5),
		0.0,
		0.0,
		sin(yaw_ned * 0.5)
	])


# ============================================================================
# 26. INPUT
# ============================================================================

func _input(
	event: InputEvent
) -> void:

	if not event is InputEventKey:
		return

	var key_event: InputEventKey = (
		event as InputEventKey
	)

	if not key_event.pressed:
		return

	if key_event.echo:
		return

	# SPACE
	if key_event.keycode == KEY_SPACE:

		add_noise_to_buoys(1.0)

		replan_from_current_position()

		return

	# RESET
	if key_event.keycode == KEY_R:

		reset_buoys()

		replan_from_current_position()

		return

	# PAUSE
	if key_event.keycode == KEY_P:

		is_paused = not is_paused

		queue_redraw()

		return

	# PAIR / SINGLE
	if key_event.keycode == KEY_TAB:

		move_buoy_pair = not move_buoy_pair

		selected_index = 0

		queue_redraw()

		return

	# RED / GREEN
	if key_event.keycode == KEY_Q:

		selected_buoy_type = (
			1 - selected_buoy_type
		)

		selected_index = 0

		queue_redraw()

		return

	# PREVIOUS
	if key_event.keycode == KEY_LEFT:

		selected_index = max(
			0,
			selected_index - 1
		)

		queue_redraw()

		return

	# NEXT
	if key_event.keycode == KEY_RIGHT:

		var maximum_index: int

		if move_buoy_pair:

			maximum_index = (
				min(
					red_balls.size(),
					green_balls.size()
				)
				-
				1
			)

		elif selected_buoy_type == 0:

			maximum_index = (
				red_balls.size() - 1
			)

		else:

			maximum_index = (
				green_balls.size() - 1
			)

		selected_index = min(
			maximum_index,
			selected_index + 1
		)

		queue_redraw()

		return

	# ------------------------------------------------------------------------
	# WASD
	# ------------------------------------------------------------------------

	var movement: Vector2 = Vector2.ZERO

	if key_event.keycode == KEY_W:

		movement = Vector2(
			0.0,
			BUOY_MOVE_STEP
		)

	elif key_event.keycode == KEY_S:

		movement = Vector2(
			0.0,
			-BUOY_MOVE_STEP
		)

	elif key_event.keycode == KEY_A:

		movement = Vector2(
			-BUOY_MOVE_STEP,
			0.0
		)

	elif key_event.keycode == KEY_D:

		movement = Vector2(
			BUOY_MOVE_STEP,
			0.0
		)

	if movement != Vector2.ZERO:

		move_selected_buoy(
			movement
		)


# ============================================================================
# 27. NOISE
# ============================================================================

func add_noise_to_buoys(
	maximum_offset: float
) -> void:

	for i: int in range(
		red_balls.size()
	):

		red_balls[i] += Vector2(
			randf_range(
				-maximum_offset,
				maximum_offset
			),

			randf_range(
				-maximum_offset,
				maximum_offset
			)
		)

	for i: int in range(
		green_balls.size()
	):

		green_balls[i] += Vector2(
			randf_range(
				-maximum_offset,
				maximum_offset
			),

			randf_range(
				-maximum_offset,
				maximum_offset
			)
		)


# ============================================================================
# 28. RESET
# ============================================================================

func reset_buoys() -> void:

	red_balls = (
		red_balls_default.duplicate(true)
	)

	green_balls = (
		green_balls_default.duplicate(true)
	)

	selected_index = 0


# ============================================================================
# 29. DYNAMIC WORLD BOUNDS
# ============================================================================

func calculate_world_bounds() -> void:

	var minimum: Vector2 = Vector2(
		INF,
		INF
	)

	var maximum: Vector2 = Vector2(
		-INF,
		-INF
	)

	var positions: Array[Vector2] = []

	positions.append(red_box)
	positions.append(green_box)
	positions.append(blue_box)
	positions.append(ship_position)

	for point: Vector2 in red_balls:
		positions.append(point)

	for point: Vector2 in green_balls:
		positions.append(point)

	for point: Vector2 in decorative_green:
		positions.append(point)

	for point: Vector2 in mission_waypoints:
		positions.append(point)

	for point: Vector2 in current_path:
		positions.append(point)

	for point: Vector2 in traveled_path:
		positions.append(point)

	if positions.is_empty():

		view_min = Vector2.ZERO
		view_max = Vector2(MAP_SIZE, MAP_SIZE)

		return

	for point: Vector2 in positions:

		minimum.x = minf(
			minimum.x,
			point.x
		)

		minimum.y = minf(
			minimum.y,
			point.y
		)

		maximum.x = maxf(
			maximum.x,
			point.x
		)

		maximum.y = maxf(
			maximum.y,
			point.y
		)

	minimum -= Vector2.ONE * WORLD_PADDING_METERS
	maximum += Vector2.ONE * WORLD_PADDING_METERS

	const MIN_VIEW_SIZE: float = 5.0

	if maximum.x - minimum.x < MIN_VIEW_SIZE:

		var center_x: float = (
			minimum.x + maximum.x
		) * 0.5

		minimum.x = center_x - MIN_VIEW_SIZE * 0.5
		maximum.x = center_x + MIN_VIEW_SIZE * 0.5

	if maximum.y - minimum.y < MIN_VIEW_SIZE:

		var center_y: float = (
			minimum.y + maximum.y
		) * 0.5

		minimum.y = center_y - MIN_VIEW_SIZE * 0.5
		maximum.y = center_y + MIN_VIEW_SIZE * 0.5

	view_min = minimum
	view_max = maximum


# ============================================================================
# 30. AUTO FIT
# ============================================================================

func update_view_transform() -> void:

	calculate_world_bounds()

	var viewport_size: Vector2 = (
		get_viewport_rect().size
	)

	var available_width: float = (
		viewport_size.x
		-
		HUD_WIDTH
		-
		VIEW_PADDING * 2.0
	)

	var available_height: float = (
		viewport_size.y
		-
		VIEW_PADDING * 2.0
	)

	available_width = maxf(
		available_width,
		100.0
	)

	available_height = maxf(
		available_height,
		100.0
	)

	var world_width: float = maxf(
		view_max.x - view_min.x,
		0.001
	)

	var world_height: float = maxf(
		view_max.y - view_min.y,
		0.001
	)

	var scale_x: float = (
		available_width / world_width
	)

	var scale_y: float = (
		available_height / world_height
	)

	draw_scale = minf(
		scale_x,
		scale_y
	)

	draw_scale = clampf(
		draw_scale,
		MIN_DRAW_SCALE,
		MAX_DRAW_SCALE
	)

	var pixel_width: float = (
		world_width * draw_scale
	)

	var pixel_height: float = (
		world_height * draw_scale
	)

	var center_x: float = (
		VIEW_PADDING
		+
		available_width * 0.5
	)

	var left: float = (
		center_x
		-
		pixel_width * 0.5
	)

	var top: float = (
		VIEW_PADDING
		+
		(
			available_height
			-
			pixel_height
		)
		* 0.5
	)

	draw_offset = Vector2(
		left,
		top
	)


# ============================================================================
# 31. WORLD TO SCREEN
# ============================================================================

func world_to_screen(
	world_position: Vector2
) -> Vector2:

	return Vector2(
		draw_offset.x
		+
		(
			world_position.x
			-
			view_min.x
		)
		*
		draw_scale,

		draw_offset.y
		+
		(
			view_max.y
			-
			world_position.y
		)
		*
		draw_scale
	)


# ============================================================================
# 32. DRAW GRID
# ============================================================================

func draw_world_grid() -> void:

	var grid_color: Color = Color(
		0.15,
		0.15,
		0.15,
		1.0
	)

	var min_x: int = int(floor(view_min.x))
	var max_x: int = int(ceil(view_max.x))

	var min_y: int = int(floor(view_min.y))
	var max_y: int = int(ceil(view_max.y))

	for x: int in range(
		min_x,
		max_x + 1
	):

		draw_line(
			world_to_screen(
				Vector2(
					float(x),
					view_min.y
				)
			),

			world_to_screen(
				Vector2(
					float(x),
					view_max.y
				)
			),

			grid_color,
			1.0
		)

	for y: int in range(
		min_y,
		max_y + 1
	):

		draw_line(
			world_to_screen(
				Vector2(
					view_min.x,
					float(y)
				)
			),

			world_to_screen(
				Vector2(
					view_max.x,
					float(y)
				)
			),

			grid_color,
			1.0
		)


# ============================================================================
# 33. DRAW PATH
# ============================================================================

func draw_path() -> void:

	if current_path.size() < 2:
		return

	for i: int in range(
		current_path.size() - 1
	):

		draw_line(
			world_to_screen(
				current_path[i]
			),

			world_to_screen(
				current_path[i + 1]
			),

			Color(
				1.0,
				0.82,
				0.05,
				0.95
			),

			3.0
		)


# ============================================================================
# 33A. DRAW TRAVELED TRAIL
# ============================================================================

func draw_traveled_path() -> void:

	if traveled_path.size() < 2:
		return

	for i: int in range(traveled_path.size() - 1):

		draw_line(
			world_to_screen(traveled_path[i]),
			world_to_screen(traveled_path[i + 1]),
			Color(1.0, 0.08, 0.05, 0.98),
			3.2
		)


# ============================================================================
# 34. DRAW BUOYS
# ============================================================================

func draw_buoys() -> void:

	for i: int in range(
		red_balls.size()
	):

		var pos: Vector2 = (
			world_to_screen(
				red_balls[i]
			)
		)

		draw_circle(
			pos,
			7.0,
			Color.RED
		)

		if (
			i == selected_index
			and
			(
				move_buoy_pair
				or
				selected_buoy_type == 0
			)
		):

			draw_circle(
				pos,
				12.0,
				Color.WHITE,
				false,
				2.0
			)

	for i: int in range(
		green_balls.size()
	):

		var pos: Vector2 = (
			world_to_screen(
				green_balls[i]
			)
		)

		draw_circle(
			pos,
			7.0,
			Color.LIME
		)

		if (
			i == selected_index
			and
			(
				move_buoy_pair
				or
				selected_buoy_type == 1
			)
		):

			draw_circle(
				pos,
				12.0,
				Color.WHITE,
				false,
				2.0
			)

	for buoy: Vector2 in decorative_green:

		draw_circle(
			world_to_screen(buoy),
			6.0,
			Color.DARK_GREEN
		)


# ============================================================================
# 35. DRAW GATES
# ============================================================================

func draw_gates() -> void:

	var gates: Array[Vector2] = (
		pair_buoys(
			red_balls,
			green_balls
		)
	)

	for i: int in range(
		gates.size()
	):

		var pos: Vector2 = (
			world_to_screen(
				gates[i]
			)
		)

		draw_circle(
			pos,
			5.0,
			Color.GOLD
		)

		draw_string(
			ThemeDB.fallback_font,

			pos + Vector2(
				7.0,
				-7.0
			),

			"G%d" % (i + 1),

			HORIZONTAL_ALIGNMENT_LEFT,

			-1,

			11,

			Color.GOLD
		)


# ============================================================================
# 36. DRAW WAYPOINTS
# ============================================================================

func draw_mission_waypoints() -> void:

	for i: int in range(
		mission_waypoints.size()
	):

		var pos: Vector2 = (
			world_to_screen(
				mission_waypoints[i]
			)
		)

		var color: Color = Color(
			0.7,
			0.2,
			1.0
		)

		if i < current_wp_index:

			color = Color(
				0.35,
				0.35,
				0.35
			)

		elif i == current_wp_index:

			color = Color.YELLOW

		draw_circle(
			pos,
			6.0,
			color,
			false,
			2.0
		)


# ============================================================================
# 37. DRAW BOX
# ============================================================================

func draw_world_box(
	world_position: Vector2,
	color: Color
) -> void:

	var top_left_world: Vector2 = (
		world_position
		+
		Vector2(
			-0.5,
			0.5
		)
	)

	var top_left: Vector2 = (
		world_to_screen(
			top_left_world
		)
	)

	draw_rect(
		Rect2(
			top_left,
			Vector2(
				draw_scale,
				draw_scale
			)
		),

		color,
		false,
		3.0
	)


func draw_boxes() -> void:

	draw_world_box(
		red_box,
		Color.DARK_RED
	)

	draw_world_box(
		green_box,
		Color.DARK_GREEN
	)

	draw_world_box(
		blue_box,
		Color.DARK_BLUE
	)


# ============================================================================
# 38. DRAW SHIP WITH REAL DIMENSIONS
# ============================================================================

func draw_ship() -> void:

	var center: Vector2 = (
		world_to_screen(
			ship_position
		)
	)

	var half_length_px: float = (
		SHIP_LENGTH
		*
		draw_scale
		*
		0.5
	)

	var half_width_px: float = (
		SHIP_WIDTH
		*
		draw_scale
		*
		0.5
	)

	# World heading vector.
	var forward_world: Vector2 = (
		Vector2.RIGHT.rotated(
			ship_heading
		)
	)

	# Screen Y terbalik.
	var forward_screen: Vector2 = Vector2(
		forward_world.x,
		-forward_world.y
	)

	var side_screen: Vector2 = Vector2(
		-forward_screen.y,
		forward_screen.x
	)

	# Kapal 1.04 m panjang.
	var front: Vector2 = (
		center
		+
		forward_screen
		*
		half_length_px
	)

	var rear: Vector2 = (
		center
		-
		forward_screen
		*
		half_length_px
	)

	var p1: Vector2 = (
		front
		+
		side_screen
		*
		half_width_px
	)

	var p2: Vector2 = (
		front
		-
		side_screen
		*
		half_width_px
	)

	var p3: Vector2 = (
		rear
		-
		side_screen
		*
		half_width_px
	)

	var p4: Vector2 = (
		rear
		+
		side_screen
		*
		half_width_px
	)

	var polygon := PackedVector2Array([
		p1,
		p2,
		p3,
		p4
	])

	draw_colored_polygon(
		polygon,
		Color(
			0.1,
			0.35,
			1.0
		)
	)

	draw_polyline(
		PackedVector2Array([
			p1,
			p2,
			p3,
			p4,
			p1
		]),
		Color.WHITE,
		2.0
	)

	draw_line(
		center,
		center
		+
		forward_screen
		*
		35.0,

		Color.CYAN,
		3.0
	)

	# Current trajectory target.
	if (
		current_path_index >= 0
		and
		current_path_index < current_path.size()
	):

		draw_circle(
			world_to_screen(
				current_path[
					current_path_index
				]
			),

			6.0,
			Color.YELLOW,
			false,
			2.0
		)


# ============================================================================
# 39. DRAW BORDER
# ============================================================================

func draw_map_border() -> void:

	var top_left: Vector2 = (
		world_to_screen(
			Vector2(
				view_min.x,
				view_max.y
			)
		)
	)

	var bottom_right: Vector2 = (
		world_to_screen(
			Vector2(
				view_max.x,
				view_min.y
			)
		)
	)

	draw_rect(
		Rect2(
			top_left,
			bottom_right - top_left
		),

		Color(
			0.65,
			0.65,
			0.65,
			0.8
		),

		false,
		2.0
	)


# ============================================================================
# 40. HUD
# ============================================================================

func draw_hud() -> void:

	var viewport_size: Vector2 = (
		get_viewport_rect().size
	)

	var hud_position: Vector2 = Vector2(
		maxf(
			viewport_size.x
			-
			HUD_WIDTH
			+
			15.0,

			10.0
		),

		25.0
	)

	var state_text: String

	if mission_complete:
		state_text = "MISSION COMPLETE"

	elif is_paused:
		state_text = "PAUSED"

	else:
		state_text = "RUNNING"

	var buoy_mode: String

	if move_buoy_pair:

		buoy_mode = "PAIR RED + GREEN"

	else:

		if selected_buoy_type == 0:
			buoy_mode = "SINGLE RED"

		else:
			buoy_mode = "SINGLE GREEN"

	var current_gate_width: float = 0.0

	if (
		selected_index >= 0
		and
		selected_index < red_balls.size()
		and
		selected_index < green_balls.size()
	):

		current_gate_width = (
			red_balls[selected_index]
			.distance_to(
				green_balls[selected_index]
			)
		)

	var required_gate_width: float = (
		GATE_REQUIRED_HALF_WIDTH
		*
		2.0
	)

	var info: String = (
		"ASV DYNAMIC PLANNER\n"
		+
		"Godot 4.5.1\n"
		+
		"\n"
		+
		"SHIP\n"
		+
		"Size: 1.04 x 0.52 m\n"
		+
		"X: %.2f m\n"
		% ship_position.x
		+
		"Y: %.2f m\n"
		% ship_position.y
		+
		"Heading: %.1f deg\n"
		% rad_to_deg(ship_heading)
		+
		"Speed: %.2f m/s\n"
		% SHIP_SPEED
		+
		"\n"
		+
		"STATE\n"
		+
		"%s\n"
		% state_text
		+
		"WP: %d / %d\n"
		%
		[
			min(
				current_wp_index + 1,
				mission_waypoints.size()
			),

			mission_waypoints.size()
		]
		+
		"Path: %d / %d\n"
		%
		[
			min(
				current_path_index + 1,
				current_path.size()
			),

			current_path.size()
		]
		+
		"\n"
		+
		"BUOY\n"
		+
		"%s\n"
		% buoy_mode
		+
		"Selected: #%d\n"
		% (selected_index + 1)
		+
		"Gate width: %.2f m\n"
		% current_gate_width
		+
		"Recommended minimum: %.2f m\n"
		% required_gate_width
		+
		"\n"
		+
		"PLANNER\n"
		+
		"Dynamic Cubic Bezier\n"
		+
		"Collision radius: %.2f m\n"
		% BUOY_SAFE_RADIUS
		+
		"Auto lookahead: ON\n"
		+
		"Live replanning: ON\n"
		+
		"Yellow: planned path\n"
		+
		"Red: traveled trail\n"
		+
		"\n"
		+
		"CONTROL\n"
		+
		"WASD: Move buoy\n"
		+
		"LEFT/RIGHT: Select\n"
		+
		"TAB: Pair/Single\n"
		+
		"Q: Red/Green\n"
		+
		"SPACE: Noise\n"
		+
		"R: Reset\n"
		+
		"P: Pause"
	)

	draw_multiline_string(
		ThemeDB.fallback_font,
		hud_position,
		info,
		HORIZONTAL_ALIGNMENT_LEFT,
		HUD_WIDTH - 30.0,
		14,
		-1,
		Color.WHITE
	)


# ============================================================================
# 41. DRAW
# ============================================================================

func _draw() -> void:

	update_view_transform()

	draw_world_grid()
	draw_map_border()

	draw_path()
	draw_traveled_path()

	draw_gates()
	draw_mission_waypoints()

	draw_buoys()
	draw_boxes()

	draw_ship()
	draw_hud()
