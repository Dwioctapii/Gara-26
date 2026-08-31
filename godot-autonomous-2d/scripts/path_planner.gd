extends Node2D

## Pengatur utama simulasi autonomous surface vehicle (ASV) 2D.
##
## File ini sengaja hanya mengatur state dan alur hidup simulasi. Perhitungan
## lintasan berada di planning/, gambar peta dan HUD berada di ui/, input keyboard
## berada di input/, sedangkan konfigurasi fisik serta MAVLink berada di core/.
## Batas tersebut membuat perilaku tiap bagian dapat dibaca tanpa menelusuri satu
## file ribuan baris.

const Config = preload("res://scripts/core/asv_config.gd")
const CoursePlanner = preload("res://scripts/planning/course_planner.gd")
const MavlinkCoordinates = preload("res://scripts/core/mavlink_coordinates.gd")

enum BuoyColor { RED, GREEN }

signal state_changed()
signal path_updated(new_path)
signal waypoint_reached(index, waypoint)
signal mission_finished()

@onready var _world_view := $WorldView
@onready var _status_hud := $UI/StatusHUD
@onready var _input_controller := $InputController

var red_buoys: Array[Vector2] = []
var green_buoys: Array[Vector2] = []
var decorative_buoys: Array[Vector2] = []

var ship_position := Config.RED_BOX
var ship_heading: float = 0.0
var current_path: Array[Vector2] = []
var mission_waypoints: Array[Vector2] = []
var traveled_path: Array[Vector2] = []
var current_path_index: int = 0
var current_wp_index: int = 0

var is_paused: bool = false
var mission_complete: bool = false

var selected_buoy_index: int = 0
var selected_buoy_type: int = BuoyColor.RED
var move_buoy_pair: bool = true

var _last_trail_position := Vector2(INF, INF)
var _course_planner := CoursePlanner.new()


func _ready() -> void:
	randomize()

	# Anak-anak node hanya menerima referensi pengatur utama. Mereka membaca
	# state yang dibutuhkan tanpa mengambil alih aturan simulasi.
	_world_view.bind(self)
	_status_hud.bind(self)
	_input_controller.bind(self)
	state_changed.connect(Callable(_world_view, "refresh"))
	state_changed.connect(Callable(_status_hud, "refresh"))

	red_buoys = Config.default_red_buoys()
	green_buoys = Config.default_green_buoys()
	decorative_buoys = Config.decorative_buoys()
	ship_position = Config.RED_BOX

	_generate_path(true)
	if not current_path.is_empty():
		ship_position = current_path[0]

	traveled_path.clear()
	_last_trail_position = Vector2(INF, INF)
	_record_traveled_point(true)
	_notify_state_changed()


func _physics_process(delta: float) -> void:
	if is_paused or mission_complete or current_path.is_empty():
		return

	if current_path_index >= current_path.size():
		mission_complete = true
		mission_finished.emit()
		_notify_state_changed()
		return

	var target := current_path[current_path_index]
	var difference := target - ship_position
	var distance := difference.length()

	if distance <= Config.PATH_POINT_RADIUS:
		current_path_index += 1
		_notify_state_changed()
		return

	var direction := difference.normalized()
	var travel_distance := minf(Config.SHIP_SPEED * delta, distance)
	ship_position += direction * travel_distance
	ship_heading = direction.angle()
	_record_traveled_point()
	_update_reached_waypoint()
	_notify_state_changed()


## Membuat ulang rute tanpa mengubah posisi, heading, status pause, atau jejak
## kapal. Inilah yang memungkinkan buoy dipindah ketika simulasi sedang berjalan.
func replan_from_current_position() -> void:
	var old_wp_index := current_wp_index
	_generate_path(false)
	current_path_index = 0
	current_wp_index = maxi(
		old_wp_index,
		_find_next_mission_waypoint(ship_position),
	)
	mission_complete = false
	_notify_state_changed()


func _generate_path(reset_mission: bool) -> void:
	mission_waypoints = _course_planner.build_mission_waypoints(
		red_buoys,
		green_buoys,
	)

	var first_target_index := 1 if reset_mission else current_wp_index
	current_path = _course_planner.generate_route(
		Config.RED_BOX if reset_mission else ship_position,
		ship_heading,
		first_target_index,
		mission_waypoints,
		red_buoys,
		green_buoys,
	)

	current_path_index = 0
	mission_complete = false
	if reset_mission:
		current_wp_index = 0

	path_updated.emit(current_path)


func _find_next_mission_waypoint(position: Vector2) -> int:
	if mission_waypoints.is_empty():
		return 0

	var start_index := clampi(
		current_wp_index,
		0,
		mission_waypoints.size() - 1,
	)
	for waypoint_index: int in range(start_index, mission_waypoints.size()):
		if position.distance_to(mission_waypoints[waypoint_index]) > Config.WAYPOINT_RADIUS:
			return waypoint_index

	return mission_waypoints.size()


func _update_reached_waypoint() -> void:
	if current_wp_index >= mission_waypoints.size():
		return

	var waypoint := mission_waypoints[current_wp_index]
	if ship_position.distance_to(waypoint) <= Config.WAYPOINT_RADIUS:
		waypoint_reached.emit(current_wp_index, waypoint)
		current_wp_index += 1


func _record_traveled_point(force: bool = false) -> void:
	if (
		force
		or _last_trail_position.x == INF
		or ship_position.distance_to(_last_trail_position)
		>= Config.TRAIL_RECORD_DISTANCE
	):
		traveled_path.append(ship_position)
		_last_trail_position = ship_position


# --- Perintah dari input ---------------------------------------------------

func toggle_pause() -> void:
	is_paused = not is_paused
	_notify_state_changed()


func toggle_buoy_move_mode() -> void:
	move_buoy_pair = not move_buoy_pair
	selected_buoy_index = 0
	_notify_state_changed()


func toggle_selected_buoy_color() -> void:
	selected_buoy_type = (
		BuoyColor.GREEN
		if selected_buoy_type == BuoyColor.RED
		else BuoyColor.RED
	)
	selected_buoy_index = 0
	_notify_state_changed()


func select_previous_buoy() -> void:
	selected_buoy_index = maxi(0, selected_buoy_index - 1)
	_notify_state_changed()


func select_next_buoy() -> void:
	selected_buoy_index = mini(
		_selection_max_index(),
		selected_buoy_index + 1,
	)
	_notify_state_changed()


func move_selected_buoy(offset: Vector2) -> void:
	if move_buoy_pair:
		if (
			selected_buoy_index < red_buoys.size()
			and selected_buoy_index < green_buoys.size()
		):
			red_buoys[selected_buoy_index] += offset
			green_buoys[selected_buoy_index] += offset
	elif selected_buoy_type == BuoyColor.RED:
		if selected_buoy_index < red_buoys.size():
			red_buoys[selected_buoy_index] += offset
	elif selected_buoy_index < green_buoys.size():
		green_buoys[selected_buoy_index] += offset

	replan_from_current_position()


func add_noise_to_buoys(maximum_offset: float = 1.0) -> void:
	for buoy_index: int in range(red_buoys.size()):
		red_buoys[buoy_index] += _random_offset(maximum_offset)
	for buoy_index: int in range(green_buoys.size()):
		green_buoys[buoy_index] += _random_offset(maximum_offset)
	replan_from_current_position()


func reset_buoys() -> void:
	red_buoys = Config.default_red_buoys()
	green_buoys = Config.default_green_buoys()
	selected_buoy_index = 0
	replan_from_current_position()


func _random_offset(maximum: float) -> Vector2:
	return Vector2(
		randf_range(-maximum, maximum),
		randf_range(-maximum, maximum),
	)


func _selection_max_index() -> int:
	if move_buoy_pair:
		return maxi(0, mini(red_buoys.size(), green_buoys.size()) - 1)
	if selected_buoy_type == BuoyColor.RED:
		return maxi(0, red_buoys.size() - 1)
	return maxi(0, green_buoys.size() - 1)


# --- Data untuk view dan integrasi luar -----------------------------------

func get_gate_centers() -> Array[Vector2]:
	return _course_planner.pair_buoys(red_buoys, green_buoys)


func is_red_buoy_highlighted(index: int) -> bool:
	return (
		index == selected_buoy_index
		and (move_buoy_pair or selected_buoy_type == BuoyColor.RED)
	)


func is_green_buoy_highlighted(index: int) -> bool:
	return (
		index == selected_buoy_index
		and (move_buoy_pair or selected_buoy_type == BuoyColor.GREEN)
	)


func get_status_snapshot() -> Dictionary:
	var selected_gate_width := 0.0
	if (
		selected_buoy_index < red_buoys.size()
		and selected_buoy_index < green_buoys.size()
	):
		selected_gate_width = red_buoys[selected_buoy_index].distance_to(
			green_buoys[selected_buoy_index]
		)

	return {
		"ship_position": ship_position,
		"ship_heading": ship_heading,
		"ship_speed": Config.SHIP_SPEED,
		"is_paused": is_paused,
		"mission_complete": mission_complete,
		"current_wp_index": current_wp_index,
		"waypoint_count": mission_waypoints.size(),
		"current_path_index": current_path_index,
		"path_point_count": current_path.size(),
		"move_buoy_pair": move_buoy_pair,
		"selected_buoy_type": selected_buoy_type,
		"selected_buoy_index": selected_buoy_index,
		"selected_gate_width": selected_gate_width,
		"required_gate_width": Config.GATE_REQUIRED_HALF_WIDTH * 2.0,
		"obstacle_margin": Config.COURSE_OBSTACLE_MARGIN,
	}


# Nama fungsi dipertahankan agar kode integrasi lama tidak perlu berubah.
func map_to_mavlink_ned(point: Vector2, height_up: float = 0.0) -> Vector3:
	return MavlinkCoordinates.map_to_local_ned(point, height_up)


func map_heading_to_mav_yaw(map_heading: float) -> float:
	return MavlinkCoordinates.heading_to_mav_yaw(map_heading)


func get_mavlink_yaw_quaternion() -> PackedFloat32Array:
	return MavlinkCoordinates.yaw_quaternion(ship_heading)


func _notify_state_changed() -> void:
	state_changed.emit()
