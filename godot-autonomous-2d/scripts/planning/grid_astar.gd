extends RefCounted

## Pembungkus tipis AStarGrid2D untuk route planner.
##
## Godot sudah menyediakan pencarian A* dan penanganan grid yang teruji. Script
## ini hanya menerjemahkan meter ke sel grid, menandai area aman di sekitar buoy,
## lalu mengembalikan titik dunia. Dengan begitu kita tidak memelihara ulang
## ratusan baris implementasi open-set, heuristic, dan pencarian tetangga.

var _grid := AStarGrid2D.new()
var _grid_size: int
var _resolution: float


func _init(
	map_size: float,
	resolution: float,
	obstacles: Array[Vector2],
	obstacle_margin: float
) -> void:
	_resolution = resolution
	_grid_size = int(ceil(map_size / resolution))

	_grid.region = Rect2i(0, 0, _grid_size, _grid_size)
	_grid.cell_size = Vector2.ONE * resolution
	_grid.offset = Vector2.ONE * resolution * 0.5
	_grid.diagonal_mode = AStarGrid2D.DIAGONAL_MODE_ALWAYS
	_grid.update()

	_mark_obstacles(obstacles, obstacle_margin)


func plan(start: Vector2, goal: Vector2) -> Array[Vector2]:
	var start_cell := _nearest_open_cell(_world_to_grid(start))
	var goal_cell := _nearest_open_cell(_world_to_grid(goal))

	if not _is_open(start_cell) or not _is_open(goal_cell):
		return []

	var grid_path: PackedVector2Array = _grid.get_point_path(start_cell, goal_cell)
	if grid_path.is_empty():
		return []

	# Pertahankan posisi asli kapal dan target. Titik AStarGrid2D berada di tengah
	# sel, sehingga tanpa dua titik ini kapal akan bergeser setengah resolusi.
	var result: Array[Vector2] = [start]
	for point: Vector2 in grid_path:
		if result[-1].distance_to(point) > 0.01:
			result.append(point)

	if result[-1].distance_to(goal) > 0.01:
		result.append(goal)

	return result


func _mark_obstacles(obstacles: Array[Vector2], margin: float) -> void:
	var radius_in_cells := int(ceil(margin / _resolution))

	for obstacle: Vector2 in obstacles:
		var center := _world_to_grid(obstacle)
		for dx: int in range(-radius_in_cells, radius_in_cells + 1):
			for dy: int in range(-radius_in_cells, radius_in_cells + 1):
				if Vector2(dx, dy).length() > float(radius_in_cells):
					continue

				var cell := center + Vector2i(dx, dy)
				if _grid.is_in_boundsv(cell):
					_grid.set_point_solid(cell, true)


func _world_to_grid(position: Vector2) -> Vector2i:
	return Vector2i(
		int(floor(position.x / _resolution)),
		int(floor(position.y / _resolution)),
	)


func _is_open(cell: Vector2i) -> bool:
	return _grid.is_in_boundsv(cell) and not _grid.is_point_solid(cell)


## Start atau goal dapat jatuh di dalam margin buoy. Pencarian cincin sederhana
## ini memindahkannya ke sel aman terdekat tanpa mengubah target dunia akhirnya.
func _nearest_open_cell(origin: Vector2i) -> Vector2i:
	if _is_open(origin):
		return origin

	for radius: int in range(1, 15):
		for dx: int in range(-radius, radius + 1):
			for dy: int in range(-radius, radius + 1):
				var candidate := origin + Vector2i(dx, dy)
				if _is_open(candidate):
					return candidate

	return origin
