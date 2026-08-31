extends Node2D

## Renderer khusus dunia simulasi.
##
## Semua posisi model memakai meter dengan X+ ke Timur dan Y+ ke Utara. Canvas
## Godot memakai Y+ ke bawah, sehingga pembalikan sumbu Y hanya dilakukan di
## _world_to_screen(). Algoritma planner tidak perlu mengetahui detail layar.

const Config = preload("res://scripts/core/asv_config.gd")

const GRID_COLOR := Color(0.15, 0.15, 0.15, 1.0)
const PATH_COLOR := Color(1.0, 0.82, 0.05, 0.95)
const TRAIL_COLOR := Color(1.0, 0.08, 0.05, 0.98)
const BORDER_COLOR := Color(0.65, 0.65, 0.65, 0.8)

var _simulation
var _draw_scale: float = 10.0
var _draw_offset := Vector2.ZERO
var _view_min := Vector2.ZERO
var _view_max := Vector2.ONE * Config.MAP_SIZE


func bind(simulation) -> void:
	_simulation = simulation
	queue_redraw()


func refresh() -> void:
	queue_redraw()


func _draw() -> void:
	if _simulation == null:
		return

	_update_view_transform()
	_draw_grid()
	_draw_map_border()
	_draw_path(_simulation.current_path, PATH_COLOR, 3.0)
	_draw_path(_simulation.traveled_path, TRAIL_COLOR, 3.2)
	_draw_gates()
	_draw_mission_waypoints()
	_draw_buoys()
	_draw_boxes()
	_draw_ship()


## Auto-fit menghitung seluruh data yang terlihat, bukan hanya buoy. Karena itu
## kapal dan jejak lama tidak terpotong setelah noise atau live replan.
func _update_view_transform() -> void:
	_calculate_world_bounds()

	var viewport_size := get_viewport_rect().size
	var available_width := maxf(
		viewport_size.x - Config.HUD_WIDTH - Config.VIEW_PADDING * 2.0,
		100.0,
	)
	var available_height := maxf(
		viewport_size.y - Config.VIEW_PADDING * 2.0,
		100.0,
	)
	var world_width := maxf(_view_max.x - _view_min.x, 0.001)
	var world_height := maxf(_view_max.y - _view_min.y, 0.001)

	_draw_scale = clampf(
		minf(available_width / world_width, available_height / world_height),
		Config.MIN_DRAW_SCALE,
		Config.MAX_DRAW_SCALE,
	)

	var pixel_size := Vector2(world_width, world_height) * _draw_scale
	var map_center_x := Config.VIEW_PADDING + available_width * 0.5
	_draw_offset = Vector2(
		map_center_x - pixel_size.x * 0.5,
		Config.VIEW_PADDING + (available_height - pixel_size.y) * 0.5,
	)


func _calculate_world_bounds() -> void:
	var positions: Array[Vector2] = [
		Config.RED_BOX,
		Config.GREEN_BOX,
		Config.BLUE_BOX,
		_simulation.ship_position,
	]
	positions.append_array(_simulation.red_buoys)
	positions.append_array(_simulation.green_buoys)
	positions.append_array(_simulation.decorative_buoys)
	positions.append_array(_simulation.mission_waypoints)
	positions.append_array(_simulation.current_path)
	positions.append_array(_simulation.traveled_path)

	var minimum := Vector2(INF, INF)
	var maximum := Vector2(-INF, -INF)
	for point: Vector2 in positions:
		minimum.x = minf(minimum.x, point.x)
		minimum.y = minf(minimum.y, point.y)
		maximum.x = maxf(maximum.x, point.x)
		maximum.y = maxf(maximum.y, point.y)

	minimum -= Vector2.ONE * Config.WORLD_PADDING_METERS
	maximum += Vector2.ONE * Config.WORLD_PADDING_METERS
	const MIN_VIEW_SIZE := 5.0

	if maximum.x - minimum.x < MIN_VIEW_SIZE:
		var center_x := (minimum.x + maximum.x) * 0.5
		minimum.x = center_x - MIN_VIEW_SIZE * 0.5
		maximum.x = center_x + MIN_VIEW_SIZE * 0.5
	if maximum.y - minimum.y < MIN_VIEW_SIZE:
		var center_y := (minimum.y + maximum.y) * 0.5
		minimum.y = center_y - MIN_VIEW_SIZE * 0.5
		maximum.y = center_y + MIN_VIEW_SIZE * 0.5

	_view_min = minimum
	_view_max = maximum


func _world_to_screen(world_position: Vector2) -> Vector2:
	return Vector2(
		_draw_offset.x + (world_position.x - _view_min.x) * _draw_scale,
		_draw_offset.y + (_view_max.y - world_position.y) * _draw_scale,
	)


func _draw_grid() -> void:
	for x: int in range(int(floor(_view_min.x)), int(ceil(_view_max.x)) + 1):
		draw_line(
			_world_to_screen(Vector2(float(x), _view_min.y)),
			_world_to_screen(Vector2(float(x), _view_max.y)),
			GRID_COLOR,
			1.0,
		)

	for y: int in range(int(floor(_view_min.y)), int(ceil(_view_max.y)) + 1):
		draw_line(
			_world_to_screen(Vector2(_view_min.x, float(y))),
			_world_to_screen(Vector2(_view_max.x, float(y))),
			GRID_COLOR,
			1.0,
		)


func _draw_path(points: Array[Vector2], color: Color, width: float) -> void:
	if points.size() < 2:
		return

	var screen_points := PackedVector2Array()
	for point: Vector2 in points:
		screen_points.append(_world_to_screen(point))
	draw_polyline(screen_points, color, width, true)


func _draw_buoys() -> void:
	for index: int in range(_simulation.red_buoys.size()):
		var position := _world_to_screen(_simulation.red_buoys[index])
		draw_circle(position, 7.0, Color.RED)
		if _simulation.is_red_buoy_highlighted(index):
			draw_circle(position, 12.0, Color.WHITE, false, 2.0)

	for index: int in range(_simulation.green_buoys.size()):
		var position := _world_to_screen(_simulation.green_buoys[index])
		draw_circle(position, 7.0, Color.LIME)
		if _simulation.is_green_buoy_highlighted(index):
			draw_circle(position, 12.0, Color.WHITE, false, 2.0)

	for buoy: Vector2 in _simulation.decorative_buoys:
		draw_circle(_world_to_screen(buoy), 6.0, Color.DARK_GREEN)


func _draw_gates() -> void:
	var gate_centers: Array[Vector2] = _simulation.get_gate_centers()
	for index: int in range(gate_centers.size()):
		var position := _world_to_screen(gate_centers[index])
		draw_circle(position, 5.0, Color.GOLD)
		draw_string(
			ThemeDB.fallback_font,
			position + Vector2(7.0, -7.0),
			"G%d" % (index + 1),
			HORIZONTAL_ALIGNMENT_LEFT,
			-1,
			11,
			Color.GOLD,
		)


func _draw_mission_waypoints() -> void:
	for index: int in range(_simulation.mission_waypoints.size()):
		var color := Color(0.7, 0.2, 1.0)
		if index < _simulation.current_wp_index:
			color = Color(0.35, 0.35, 0.35)
		elif index == _simulation.current_wp_index:
			color = Color.YELLOW

		draw_circle(
			_world_to_screen(_simulation.mission_waypoints[index]),
			6.0,
			color,
			false,
			2.0,
		)


func _draw_boxes() -> void:
	_draw_world_box(Config.RED_BOX, Color.DARK_RED)
	_draw_world_box(Config.GREEN_BOX, Color.DARK_GREEN)
	_draw_world_box(Config.BLUE_BOX, Color.DARK_BLUE)


func _draw_world_box(world_position: Vector2, color: Color) -> void:
	var top_left := _world_to_screen(world_position + Vector2(-0.5, 0.5))
	draw_rect(
		Rect2(top_left, Vector2.ONE * _draw_scale),
		color,
		false,
		3.0,
	)


func _draw_ship() -> void:
	var center := _world_to_screen(_simulation.ship_position)
	var half_length := Config.SHIP_LENGTH * _draw_scale * 0.5
	var half_width := Config.SHIP_WIDTH * _draw_scale * 0.5
	var forward_world := Vector2.RIGHT.rotated(_simulation.ship_heading)
	var forward_screen := Vector2(forward_world.x, -forward_world.y)
	var side_screen := Vector2(-forward_screen.y, forward_screen.x)

	var front := center + forward_screen * half_length
	var rear := center - forward_screen * half_length
	var corners := PackedVector2Array([
		front + side_screen * half_width,
		front - side_screen * half_width,
		rear - side_screen * half_width,
		rear + side_screen * half_width,
	])

	draw_colored_polygon(corners, Color(0.1, 0.35, 1.0))
	var outline := corners.duplicate()
	outline.append(corners[0])
	draw_polyline(outline, Color.WHITE, 2.0, true)
	draw_line(center, center + forward_screen * 35.0, Color.CYAN, 3.0)

	if (
		_simulation.current_path_index >= 0
		and _simulation.current_path_index < _simulation.current_path.size()
	):
		draw_circle(
			_world_to_screen(
				_simulation.current_path[_simulation.current_path_index]
			),
			6.0,
			Color.YELLOW,
			false,
			2.0,
		)


func _draw_map_border() -> void:
	var top_left := _world_to_screen(Vector2(_view_min.x, _view_max.y))
	var bottom_right := _world_to_screen(Vector2(_view_max.x, _view_min.y))
	draw_rect(Rect2(top_left, bottom_right - top_left), BORDER_COLOR, false, 2.0)
