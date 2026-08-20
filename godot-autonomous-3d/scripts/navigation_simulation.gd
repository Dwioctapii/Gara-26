extends Node

## Flat-surface ASV navigation model.
## Planner coordinates are Vector2(East, North), in metres.

signal path_updated(path: Array[Vector2])
signal state_updated
signal mission_finished

enum PlayMode {
	SELECT,
	DEMO,
	REAL
}

const MAP_SIZE := 35.0
const GRID_RESOLUTION := 0.5
const OBSTACLE_MARGIN := 0.58
const SHIP_SPEED := 2.0
const PATH_POINT_RADIUS := 0.24
const WAYPOINT_RADIUS := 0.85
const BUOY_MOVE_STEP := 0.5
const BEZIER_MISSION_LEG := 3
const LINEAR_LEG_START := 4
const LINEAR_LEG_END := 7
const SMOOTH_TAIL_START_WAYPOINT := 7
const SAFE_GATE_8_TO_9_LEG := 8
const SPLINE_STEPS_PER_SEGMENT := 20

var red_box := Vector2(20.5, 0.0)
var green_box := Vector2(5.5, 1.0)
var blue_box := Vector2(2.5, 4.0)

var red_balls_default: Array[Vector2] = [
	Vector2(20.0, 7.0), Vector2(18.7, 10.0),
	Vector2(20.5, 12.6), Vector2(14.5, 18.5),
	Vector2(12.5, 18.5), Vector2(10.5, 18.5),
	Vector2(8.5, 18.5), Vector2(1.5, 15.0),
	Vector2(0.0, 11.5), Vector2(0.0, 7.5)
]

var green_balls_default: Array[Vector2] = [
	Vector2(21.5, 7.0), Vector2(20.2, 10.0),
	Vector2(22.1, 12.6), Vector2(14.5, 20.0),
	Vector2(12.5, 20.0), Vector2(10.5, 20.0),
	Vector2(8.5, 20.0), Vector2(3.0, 15.0),
	Vector2(1.3, 11.5), Vector2(1.3, 7.5)
]

var red_balls: Array[Vector2] = []
var green_balls: Array[Vector2] = []
var mission_waypoints: Array[Vector2] = []
var current_path: Array[Vector2] = []
var traveled_path: Array[Vector2] = []

var ship_position := Vector2.ZERO
var ship_heading := 0.0
var current_path_index := 0
var current_wp_index := 1
var is_paused := false
var mission_complete := false
var play_mode: PlayMode = PlayMode.SELECT

var selected_index := 0
var selected_buoy_type := 0 # 0 red, 1 green
var move_buoy_pair := true
var _last_track_position := Vector2(INF, INF)


func _ready() -> void:
	randomize()
	reset_buoys(false)
	mission_waypoints = build_mission_waypoints()
	ship_position = red_box
	current_wp_index = 1
	generate_path()
	_record_track_point(true)


func _physics_process(delta: float) -> void:
	# SELECT waits for T/B. REAL receives its pose from MavlinkListener.
	if play_mode != PlayMode.DEMO:
		return
	if is_paused or mission_complete or current_path.is_empty():
		return

	if current_path_index >= current_path.size():
		mission_complete = true
		mission_finished.emit()
		state_updated.emit()
		return

	var target := current_path[current_path_index]
	var difference := target - ship_position
	var distance := difference.length()

	if distance <= PATH_POINT_RADIUS:
		current_path_index += 1
		return

	var direction := difference.normalized()
	var travel_distance := minf(SHIP_SPEED * delta, distance)
	ship_position += direction * travel_distance
	ship_heading = direction.angle()
	_record_track_point()
	_update_mission_progress()
	state_updated.emit()


func pair_buoys() -> Array[Vector2]:
	var result: Array[Vector2] = []
	var used_green: Array[int] = []

	for red in red_balls:
		var best_index := -1
		var best_distance := INF
		for i in range(green_balls.size()):
			if used_green.has(i):
				continue
			var distance := red.distance_to(green_balls[i])
			if distance < best_distance:
				best_distance = distance
				best_index = i
		if best_index >= 0:
			used_green.append(best_index)
			result.append((red + green_balls[best_index]) * 0.5)

	return result


func build_mission_waypoints() -> Array[Vector2]:
	var result: Array[Vector2] = [red_box]
	result.append_array(pair_buoys())
	result.append(Vector2(blue_box.x - 1.5, 5.0))
	result.append(Vector2(2.5, green_box.y + 1.0))
	result.append(Vector2(10.0, green_box.y + 1.0))
	result.append(red_box)
	return result


func generate_path() -> void:
	mission_waypoints = build_mission_waypoints()
	var route: Array[Vector2] = [ship_position]

	for i in range(current_wp_index, mission_waypoints.size()):
		# Smoothly enter gate 8. The curve departs gate 7 perpendicular to its
		# buoy line and arrives at gate 8 vertically, through its midpoint.
		# The next curve continues with the same tangent, so no hard turn occurs.
		if i == SMOOTH_TAIL_START_WAYPOINT + 1 and i + 1 < mission_waypoints.size():
			var arrival_start: Vector2 = route[-1]
			var arrival_goal: Vector2 = mission_waypoints[i]
			var gate_8_arrival := _cubic_bezier(
				arrival_start,
				arrival_start + Vector2(-2.0, 0.0),
				arrival_goal + Vector2(0.0, 1.2),
				arrival_goal,
				30
			)
			for arrival_index in range(1, gate_8_arrival.size()):
				route.append(gate_8_arrival[arrival_index])
			continue

		# Continue the remaining course with a smooth tail after the dedicated
		# straight gate 8 -> 9 leg has been appended.
		if i > SAFE_GATE_8_TO_9_LEG + 1:
			var tail_controls: Array[Vector2] = [route[-1]]
			for tail_index in range(i, mission_waypoints.size()):
				tail_controls.append(mission_waypoints[tail_index])
			var smooth_tail := _catmull_rom(tail_controls, SPLINE_STEPS_PER_SEGMENT)
			for tail_point_index in range(1, smooth_tail.size()):
				if route[-1].distance_to(smooth_tail[tail_point_index]) > 0.001:
					route.append(smooth_tail[tail_point_index])
			break

		var mission_leg := i - 1
		var preserve_shape := false
		var segment: Array[Vector2] = []

		# Restore the routing rules from the original 2D planner. The turn
		# from gate 3 to gate 4 must bow around the course instead of being
		# flattened into a direct diagonal shortcut.
		if mission_leg == BEZIER_MISSION_LEG:
			segment = _quadratic_bezier(
				route[-1],
				Vector2(20.0, 20.0),
				mission_waypoints[i],
				60
			)
			preserve_shape = true
		elif mission_leg == SAFE_GATE_8_TO_9_LEG:
			# Two vertical tangents keep the vessel centered between both
			# horizontal buoy pairs and give 0.65 m minimum centre clearance.
			segment = _cubic_bezier(
				route[-1],
				route[-1] + Vector2(0.0, -1.2),
				mission_waypoints[i] + Vector2(0.0, 1.2),
				mission_waypoints[i],
				30
			)
			preserve_shape = true
		elif (
			mission_leg >= LINEAR_LEG_START
			and mission_leg < LINEAR_LEG_END
		):
			segment = _interpolate_line(route[-1], mission_waypoints[i], 30)
			preserve_shape = true
		else:
			segment = _plan_segment(route[-1], mission_waypoints[i])

		if segment.size() < 2:
			segment = _interpolate_line(route[-1], mission_waypoints[i], 12)
		# Simplify only inside one mission leg. Simplifying the complete loop
		# would connect the identical start/end box and skip every gate.
		# Never simplify designed Bezier/linear course segments: doing so would
		# turn the Bezier back into the diagonal cut it was meant to prevent.
		if not preserve_shape:
			segment = _simplify_path(segment)
		for j in range(1, segment.size()):
			if route[-1].distance_to(segment[j]) > 0.01:
				route.append(segment[j])

	current_path = route
	current_path_index = 1 if current_path.size() > 1 else 0
	mission_complete = false
	path_updated.emit(current_path)
	state_updated.emit()


func _plan_segment(start: Vector2, goal: Vector2) -> Array[Vector2]:
	var grid := AStarGrid2D.new()
	var grid_side := int(ceil(MAP_SIZE / GRID_RESOLUTION)) + 1
	grid.region = Rect2i(0, 0, grid_side, grid_side)
	grid.cell_size = Vector2(GRID_RESOLUTION, GRID_RESOLUTION)
	grid.diagonal_mode = AStarGrid2D.DIAGONAL_MODE_ONLY_IF_NO_OBSTACLES
	grid.update()

	var obstacles: Array[Vector2] = []
	obstacles.append_array(red_balls)
	obstacles.append_array(green_balls)

	var radius_cells := int(ceil(OBSTACLE_MARGIN / GRID_RESOLUTION))
	for obstacle in obstacles:
		var center := _world_to_grid(obstacle, grid_side)
		for dx in range(-radius_cells, radius_cells + 1):
			for dy in range(-radius_cells, radius_cells + 1):
				var cell := center + Vector2i(dx, dy)
				if not grid.region.has_point(cell):
					continue
				if _grid_to_world(cell).distance_to(obstacle) <= OBSTACLE_MARGIN:
					grid.set_point_solid(cell, true)

	var start_cell := _nearest_open_cell(grid, _world_to_grid(start, grid_side))
	var goal_cell := _nearest_open_cell(grid, _world_to_grid(goal, grid_side))
	if grid.is_point_solid(start_cell) or grid.is_point_solid(goal_cell):
		return []

	var ids: Array[Vector2i] = grid.get_id_path(start_cell, goal_cell)
	if ids.is_empty():
		return []

	var result: Array[Vector2] = [start]
	for id in ids:
		var point := _grid_to_world(id)
		if result[-1].distance_to(point) > 0.01:
			result.append(point)
	if result[-1].distance_to(goal) > 0.01:
		result.append(goal)
	return result


func _nearest_open_cell(grid: AStarGrid2D, origin: Vector2i) -> Vector2i:
	if grid.region.has_point(origin) and not grid.is_point_solid(origin):
		return origin
	for radius in range(1, 12):
		for dx in range(-radius, radius + 1):
			for dy in range(-radius, radius + 1):
				var candidate := origin + Vector2i(dx, dy)
				if grid.region.has_point(candidate) and not grid.is_point_solid(candidate):
					return candidate
	return origin


func _world_to_grid(point: Vector2, side: int) -> Vector2i:
	return Vector2i(
		clampi(int(round(point.x / GRID_RESOLUTION)), 0, side - 1),
		clampi(int(round(point.y / GRID_RESOLUTION)), 0, side - 1)
	)


func _grid_to_world(cell: Vector2i) -> Vector2:
	return Vector2(cell.x, cell.y) * GRID_RESOLUTION


func _simplify_path(path: Array[Vector2]) -> Array[Vector2]:
	if path.size() < 3:
		return path
	var result: Array[Vector2] = [path[0]]
	var anchor := 0
	while anchor < path.size() - 1:
		var furthest := anchor + 1
		for candidate in range(path.size() - 1, anchor, -1):
			if _segment_is_clear(path[anchor], path[candidate]):
				furthest = candidate
				break
		result.append(path[furthest])
		anchor = furthest
	return _densify_path(result, 0.35)


func _segment_is_clear(a: Vector2, b: Vector2) -> bool:
	var distance := a.distance_to(b)
	var samples := maxi(2, int(ceil(distance / 0.18)))
	for i in range(samples + 1):
		var point := a.lerp(b, float(i) / float(samples))
		for buoy in red_balls:
			if point.distance_to(buoy) < OBSTACLE_MARGIN:
				return false
		for buoy in green_balls:
			if point.distance_to(buoy) < OBSTACLE_MARGIN:
				return false
	return true


func _densify_path(path: Array[Vector2], spacing: float) -> Array[Vector2]:
	var result: Array[Vector2] = []
	if path.is_empty():
		return result
	result.append(path[0])
	for i in range(path.size() - 1):
		var distance := path[i].distance_to(path[i + 1])
		var steps := maxi(1, int(ceil(distance / spacing)))
		for j in range(1, steps + 1):
			result.append(path[i].lerp(path[i + 1], float(j) / float(steps)))
	return result


func _interpolate_line(a: Vector2, b: Vector2, steps: int) -> Array[Vector2]:
	var result: Array[Vector2] = []
	for i in range(steps + 1):
		result.append(a.lerp(b, float(i) / float(steps)))
	return result


func _quadratic_bezier(start: Vector2, control: Vector2, goal: Vector2, steps: int) -> Array[Vector2]:
	var result: Array[Vector2] = []
	for i in range(steps + 1):
		var t := float(i) / float(steps)
		var inverse_t := 1.0 - t
		result.append(
			inverse_t * inverse_t * start
			+ 2.0 * inverse_t * t * control
			+ t * t * goal
		)
	return result


func _cubic_bezier(start: Vector2, control_1: Vector2, control_2: Vector2, goal: Vector2, steps: int) -> Array[Vector2]:
	var result: Array[Vector2] = []
	for i in range(steps + 1):
		var t := float(i) / float(steps)
		var inverse_t := 1.0 - t
		result.append(
			inverse_t * inverse_t * inverse_t * start
			+ 3.0 * inverse_t * inverse_t * t * control_1
			+ 3.0 * inverse_t * t * t * control_2
			+ t * t * t * goal
		)
	return result


func _catmull_rom(points: Array[Vector2], steps_per_segment: int) -> Array[Vector2]:
	if points.size() < 2:
		return points.duplicate()
	if points.size() == 2:
		return _interpolate_line(points[0], points[1], steps_per_segment)

	var extended: Array[Vector2] = [points[0]]
	extended.append_array(points)
	extended.append(points[-1])
	var result: Array[Vector2] = []

	for segment_index in range(1, extended.size() - 2):
		var p0 := extended[segment_index - 1]
		var p1 := extended[segment_index]
		var p2 := extended[segment_index + 1]
		var p3 := extended[segment_index + 2]
		for step in range(steps_per_segment + 1):
			if segment_index > 1 and step == 0:
				continue
			var t := float(step) / float(steps_per_segment)
			var t2 := t * t
			var t3 := t2 * t
			result.append(0.5 * (
				2.0 * p1
				+ (-p0 + p2) * t
				+ (2.0 * p0 - 5.0 * p1 + 4.0 * p2 - p3) * t2
				+ (-p0 + 3.0 * p1 - 3.0 * p2 + p3) * t3
			))
	return result


func _update_mission_progress() -> void:
	if current_wp_index >= mission_waypoints.size():
		return
	if ship_position.distance_to(mission_waypoints[current_wp_index]) <= WAYPOINT_RADIUS:
		current_wp_index += 1
		if current_wp_index >= mission_waypoints.size():
			mission_complete = true
			mission_finished.emit()


func _record_track_point(force := false) -> void:
	if force or _last_track_position.x == INF or ship_position.distance_to(_last_track_position) >= 0.18:
		traveled_path.append(ship_position)
		_last_track_position = ship_position


func reset_buoys(replan := true) -> void:
	red_balls = red_balls_default.duplicate(true)
	green_balls = green_balls_default.duplicate(true)
	selected_index = 0
	if replan:
		generate_path()


func add_noise_to_buoys(maximum_offset := 0.8) -> void:
	for i in range(red_balls.size()):
		red_balls[i] += Vector2(
			randf_range(-maximum_offset, maximum_offset),
			randf_range(-maximum_offset, maximum_offset)
		)
	for i in range(green_balls.size()):
		green_balls[i] += Vector2(
			randf_range(-maximum_offset, maximum_offset),
			randf_range(-maximum_offset, maximum_offset)
		)
	generate_path()


func move_selected_buoy(movement: Vector2) -> void:
	if move_buoy_pair:
		if selected_index < red_balls.size():
			red_balls[selected_index] += movement
		if selected_index < green_balls.size():
			green_balls[selected_index] += movement
	elif selected_buoy_type == 0 and selected_index < red_balls.size():
		red_balls[selected_index] += movement
	elif selected_buoy_type == 1 and selected_index < green_balls.size():
		green_balls[selected_index] += movement
	generate_path()


func _unhandled_input(event: InputEvent) -> void:
	if not event is InputEventKey or not event.pressed or event.echo:
		return

	match event.keycode:
		KEY_D:
			move_selected_buoy(Vector2(BUOY_MOVE_STEP, 0.0))
		KEY_P:
			is_paused = not is_paused
			state_updated.emit()
		KEY_R:
			reset_buoys()
		KEY_SPACE:
			add_noise_to_buoys()
		KEY_TAB:
			move_buoy_pair = not move_buoy_pair
			selected_index = 0
			state_updated.emit()
		KEY_Q:
			selected_buoy_type = 1 - selected_buoy_type
			selected_index = 0
			state_updated.emit()
		KEY_LEFT:
			selected_index = maxi(0, selected_index - 1)
			state_updated.emit()
		KEY_RIGHT:
			var count := mini(red_balls.size(), green_balls.size()) if move_buoy_pair else (red_balls.size() if selected_buoy_type == 0 else green_balls.size())
			selected_index = mini(count - 1, selected_index + 1)
			state_updated.emit()
		KEY_W:
			move_selected_buoy(Vector2(0.0, BUOY_MOVE_STEP))
		KEY_S:
			move_selected_buoy(Vector2(0.0, -BUOY_MOVE_STEP))
		KEY_A:
			move_selected_buoy(Vector2(-BUOY_MOVE_STEP, 0.0))
func set_play_mode(new_mode: PlayMode) -> void:
	play_mode = new_mode
	is_paused = false
	if new_mode == PlayMode.DEMO and (mission_complete or current_path_index >= current_path.size()):
		restart_demo()
	state_updated.emit()


func get_play_mode_name() -> String:
	match play_mode:
		PlayMode.DEMO:
			return "DEMO / AUTONOMOUS"
		PlayMode.REAL:
			return "REAL / MAVLINK"
		_:
			return "SELECT MODE"


func is_real_mode() -> bool:
	return play_mode == PlayMode.REAL


func is_select_mode() -> bool:
	return play_mode == PlayMode.SELECT


func start_demo() -> void:
	set_play_mode(PlayMode.DEMO)


func start_real() -> void:
	set_play_mode(PlayMode.REAL)


func restart_demo() -> void:
	ship_position = red_box
	ship_heading = 0.0
	current_wp_index = 1
	current_path_index = 0
	mission_complete = false
	traveled_path.clear()
	_last_track_position = Vector2(INF, INF)
	generate_path()
	_record_track_point(true)


## Called by the MAVLink listener after receiving LOCAL_POSITION_NED.
func apply_mavlink_position_ned(position_ned: Vector3) -> void:
	if play_mode != PlayMode.REAL:
		return
	ship_position = Vector2(position_ned.y, position_ned.x)
	_record_track_point()
	_update_mission_progress()
	state_updated.emit()


## Called by the MAVLink listener after receiving ATTITUDE or
## ATTITUDE_QUATERNION. Input yaw uses NED convention.
func apply_mavlink_yaw(yaw_ned: float) -> void:
	if play_mode != PlayMode.REAL:
		return
	ship_heading = wrapf(PI * 0.5 - yaw_ned, -PI, PI)
	state_updated.emit()


## Planner Vector2(East, North) -> MAVLink LOCAL_NED(North, East, Down).
func map_to_mavlink_ned(point: Vector2, height_up := 0.0) -> Vector3:
	return Vector3(point.y, point.x, -height_up)


## Planner heading: zero East, CCW positive. MAVLink yaw: zero North,
## clockwise positive when viewed from above in the NED frame.
func map_heading_to_mav_yaw(map_heading: float) -> float:
	return wrapf(PI * 0.5 - map_heading, -PI, PI)


## Returns MAVLink order (w, x, y, z), for a flat vessel (roll=pitch=0).
func get_mavlink_yaw_quaternion() -> PackedFloat32Array:
	var yaw_ned := map_heading_to_mav_yaw(ship_heading)
	return PackedFloat32Array([
		cos(yaw_ned * 0.5), 0.0, 0.0, sin(yaw_ned * 0.5)
	])
