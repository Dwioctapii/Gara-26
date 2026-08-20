extends Control

@export var simulation_path: NodePath

const PADDING := 22.0
var simulation: Node
var view_min := Vector2.ZERO
var view_max := Vector2(35.0, 35.0)
var draw_scale := 1.0
var draw_origin := Vector2.ZERO


func _ready() -> void:
	simulation = get_node(simulation_path)
	simulation.path_updated.connect(_on_path_updated)
	queue_redraw()


func _process(_delta: float) -> void:
	queue_redraw()


func _on_path_updated(_path: Array[Vector2]) -> void:
	queue_redraw()


func _draw() -> void:
	draw_rect(Rect2(Vector2.ZERO, size), Color(0.018, 0.032, 0.052, 0.94), true)
	draw_rect(Rect2(Vector2.ZERO, size), Color(0.35, 0.68, 0.78, 0.85), false, 2.0)
	_update_transform()
	_draw_grid()
	# Yellow = planned path; red = vessel trail already travelled.
	_draw_line_path(simulation.current_path, Color(1.0, 0.82, 0.05, 0.98), 2.6)
	_draw_line_path(simulation.traveled_path, Color(1.0, 0.08, 0.05, 0.98), 2.2)
	_draw_waypoints()
	_draw_buoys()
	_draw_boxes()
	_draw_ship()
	draw_string(ThemeDB.fallback_font, Vector2(12.0, 19.0), "2D MAP — YELLOW planned / RED travelled", HORIZONTAL_ALIGNMENT_LEFT, -1.0, 13, Color(0.8, 0.94, 1.0))


func _update_transform() -> void:
	view_min = Vector2(INF, INF)
	view_max = Vector2(-INF, -INF)
	var points: Array[Vector2] = [simulation.red_box, simulation.green_box, simulation.blue_box, simulation.ship_position]
	points.append_array(simulation.red_balls)
	points.append_array(simulation.green_balls)
	points.append_array(simulation.current_path)
	for point in points:
		view_min.x = minf(view_min.x, point.x)
		view_min.y = minf(view_min.y, point.y)
		view_max.x = maxf(view_max.x, point.x)
		view_max.y = maxf(view_max.y, point.y)
	view_min -= Vector2.ONE * 1.4
	view_max += Vector2.ONE * 1.4
	var world_size := view_max - view_min
	var available := size - Vector2.ONE * PADDING * 2.0
	draw_scale = minf(available.x / maxf(world_size.x, 0.1), available.y / maxf(world_size.y, 0.1))
	var used := world_size * draw_scale
	draw_origin = Vector2(
		(size.x - used.x) * 0.5,
		(size.y - used.y) * 0.5
	)


func world_to_map(point: Vector2) -> Vector2:
	return Vector2(
		draw_origin.x + (point.x - view_min.x) * draw_scale,
		draw_origin.y + (view_max.y - point.y) * draw_scale
	)


func _draw_grid() -> void:
	var color := Color(0.18, 0.34, 0.42, 0.48)
	for x in range(int(floor(view_min.x)), int(ceil(view_max.x)) + 1):
		draw_line(world_to_map(Vector2(float(x), view_min.y)), world_to_map(Vector2(float(x), view_max.y)), color, 1.0)
	for y in range(int(floor(view_min.y)), int(ceil(view_max.y)) + 1):
		draw_line(world_to_map(Vector2(view_min.x, float(y))), world_to_map(Vector2(view_max.x, float(y))), color, 1.0)


func _draw_line_path(path: Array[Vector2], color: Color, width: float) -> void:
	if path.size() < 2:
		return
	var screen_points := PackedVector2Array()
	for point in path:
		screen_points.append(world_to_map(point))
	draw_polyline(screen_points, color, width, true)


func _draw_waypoints() -> void:
	for i in range(simulation.mission_waypoints.size()):
		var color := Color(0.65, 0.35, 1.0)
		if i < simulation.current_wp_index:
			color = Color(0.38, 0.42, 0.46)
		elif i == simulation.current_wp_index:
			color = Color.YELLOW
		var point := world_to_map(simulation.mission_waypoints[i])
		draw_circle(point, 4.0, color, false, 1.5)


func _draw_buoys() -> void:
	for i in range(simulation.red_balls.size()):
		var selected: bool = i == simulation.selected_index and (simulation.move_buoy_pair or simulation.selected_buoy_type == 0)
		_draw_buoy(simulation.red_balls[i], Color(1.0, 0.08, 0.05), selected)
	for i in range(simulation.green_balls.size()):
		var selected: bool = i == simulation.selected_index and (simulation.move_buoy_pair or simulation.selected_buoy_type == 1)
		_draw_buoy(simulation.green_balls[i], Color(0.05, 1.0, 0.18), selected)


func _draw_buoy(point: Vector2, color: Color, selected: bool) -> void:
	var screen_point := world_to_map(point)
	draw_circle(screen_point, 4.5, color)
	if selected:
		draw_circle(screen_point, 8.5, Color.WHITE, false, 1.8)


func _draw_boxes() -> void:
	_draw_box(simulation.red_box, Color(0.9, 0.05, 0.05))
	_draw_box(simulation.green_box, Color(0.05, 0.8, 0.12))
	_draw_box(simulation.blue_box, Color(0.08, 0.28, 1.0))


func _draw_box(point: Vector2, color: Color) -> void:
	var center := world_to_map(point)
	draw_rect(Rect2(center - Vector2.ONE * 5.0, Vector2.ONE * 10.0), color, false, 2.0)


func _draw_ship() -> void:
	var center := world_to_map(simulation.ship_position)
	var forward_world := Vector2.RIGHT.rotated(simulation.ship_heading)
	var forward_screen := Vector2(forward_world.x, -forward_world.y)
	var side := forward_screen.orthogonal()
	var polygon := PackedVector2Array([
		center + forward_screen * 10.0,
		center - forward_screen * 6.5 + side * 5.0,
		center - forward_screen * 6.5 - side * 5.0
	])
	draw_colored_polygon(polygon, Color(0.12, 0.52, 1.0))
	draw_polyline(PackedVector2Array([polygon[0], polygon[1], polygon[2], polygon[0]]), Color(0.5, 0.95, 1.0), 1.4)
