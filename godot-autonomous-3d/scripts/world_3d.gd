extends Node3D

@export var simulation_path: NodePath

var simulation: Node
var ship: Node3D
var buoy_container: Node3D
var planned_line: MeshInstance3D
var traveled_line: MeshInstance3D
var camera: Camera3D
var follow_camera := false
var _track_size_drawn := -1


func _ready() -> void:
	simulation = get_node(simulation_path)
	_build_environment()
	_build_ocean()
	_build_course_grid()
	_build_ship()
	_build_camera()
	buoy_container = Node3D.new()
	buoy_container.name = "Buoys"
	add_child(buoy_container)

	planned_line = MeshInstance3D.new()
	planned_line.name = "PlannedTrajectory"
	add_child(planned_line)
	traveled_line = MeshInstance3D.new()
	traveled_line.name = "TraveledTrajectory"
	add_child(traveled_line)

	simulation.path_updated.connect(_on_path_updated)
	_on_path_updated(simulation.current_path)


func _process(delta: float) -> void:
	if not is_instance_valid(ship):
		return

	var position_2d: Vector2 = simulation.ship_position
	ship.position = navigation_to_3d(position_2d, 0.24)
	ship.rotation.y = simulation.ship_heading - PI * 0.5

	if simulation.traveled_path.size() != _track_size_drawn:
		_track_size_drawn = simulation.traveled_path.size()
		_draw_polyline(traveled_line, simulation.traveled_path, Color(1.0, 0.06, 0.03), 0.12)

	if follow_camera:
		var forward := Vector3(
			cos(simulation.ship_heading),
			0.0,
			-sin(simulation.ship_heading)
		)
		var target_position := ship.global_position - forward * 7.0 + Vector3.UP * 5.0
		camera.global_position = camera.global_position.lerp(target_position, minf(1.0, delta * 2.5))
		camera.look_at(ship.global_position + forward * 2.0, Vector3.UP)


func _unhandled_input(event: InputEvent) -> void:
	if event is InputEventKey and event.pressed and not event.echo and event.keycode == KEY_C:
		follow_camera = not follow_camera
		if not follow_camera:
			_set_overview_camera()


func navigation_to_3d(point: Vector2, height := 0.0) -> Vector3:
	return Vector3(point.x, height, -point.y)


func _on_path_updated(path: Array[Vector2]) -> void:
	_draw_polyline(planned_line, path, Color(1.0, 0.78, 0.03), 0.16)
	_rebuild_buoys()


func _build_environment() -> void:
	var environment_node := WorldEnvironment.new()
	var environment := Environment.new()
	environment.background_mode = Environment.BG_COLOR
	environment.background_color = Color(0.035, 0.065, 0.10)
	environment.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
	environment.ambient_light_color = Color(0.55, 0.68, 0.8)
	environment.ambient_light_energy = 0.75
	environment.tonemap_mode = Environment.TONE_MAPPER_FILMIC
	environment_node.environment = environment
	add_child(environment_node)

	var light := DirectionalLight3D.new()
	light.rotation_degrees = Vector3(-55.0, -28.0, 0.0)
	light.light_energy = 1.1
	light.shadow_enabled = true
	add_child(light)


func _build_ocean() -> void:
	var ocean := MeshInstance3D.new()
	var plane := PlaneMesh.new()
	plane.size = Vector2(38.0, 38.0)
	ocean.mesh = plane
	ocean.position = Vector3(MAP_CENTER.x, 0.0, MAP_CENTER.z)
	ocean.material_override = _make_material(Color(0.025, 0.26, 0.38), 0.78, 0.18)
	add_child(ocean)


const MAP_CENTER := Vector3(17.5, 0.0, -17.5)


func _build_course_grid() -> void:
	var grid_mesh := ImmediateMesh.new()
	var grid_material := _make_material(Color(0.25, 0.58, 0.68, 0.34), 1.0, 0.0)
	grid_material.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA
	grid_material.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	grid_mesh.surface_begin(Mesh.PRIMITIVE_LINES, grid_material)
	for meter in range(0, 36):
		grid_mesh.surface_add_vertex(navigation_to_3d(Vector2(float(meter), 0.0), 0.025))
		grid_mesh.surface_add_vertex(navigation_to_3d(Vector2(float(meter), 35.0), 0.025))
		grid_mesh.surface_add_vertex(navigation_to_3d(Vector2(0.0, float(meter)), 0.025))
		grid_mesh.surface_add_vertex(navigation_to_3d(Vector2(35.0, float(meter)), 0.025))
	grid_mesh.surface_end()
	var grid_instance := MeshInstance3D.new()
	grid_instance.mesh = grid_mesh
	add_child(grid_instance)


func _build_camera() -> void:
	camera = Camera3D.new()
	camera.current = true
	camera.fov = 52.0
	add_child(camera)
	_set_overview_camera()


func _set_overview_camera() -> void:
	camera.position = Vector3(17.5, 29.0, 18.0)
	camera.look_at(Vector3(12.0, 0.0, -10.0), Vector3.UP)


func _build_ship() -> void:
	ship = Node3D.new()
	ship.name = "ASV"
	add_child(ship)

	var hull := MeshInstance3D.new()
	var hull_mesh := BoxMesh.new()
	hull_mesh.size = Vector3(0.9, 0.28, 1.8)
	hull.mesh = hull_mesh
	hull.material_override = _make_material(Color(0.05, 0.28, 0.7), 0.42, 0.25)
	ship.add_child(hull)

	var deck := MeshInstance3D.new()
	var deck_mesh := BoxMesh.new()
	deck_mesh.size = Vector3(0.58, 0.25, 0.72)
	deck.mesh = deck_mesh
	deck.position = Vector3(0.0, 0.25, 0.18)
	deck.material_override = _make_material(Color(0.82, 0.9, 0.95), 0.55, 0.05)
	ship.add_child(deck)

	var bow := MeshInstance3D.new()
	var bow_mesh := CylinderMesh.new()
	bow_mesh.top_radius = 0.0
	bow_mesh.bottom_radius = 0.46
	bow_mesh.height = 0.68
	bow_mesh.radial_segments = 4
	bow.mesh = bow_mesh
	bow.position = Vector3(0.0, 0.0, -1.18)
	bow.rotation_degrees.x = 90.0
	bow.material_override = hull.material_override
	ship.add_child(bow)

	var heading_marker := MeshInstance3D.new()
	var marker_mesh := BoxMesh.new()
	marker_mesh.size = Vector3(0.10, 0.08, 0.72)
	heading_marker.mesh = marker_mesh
	heading_marker.position = Vector3(0.0, 0.22, -0.72)
	heading_marker.material_override = _make_material(Color(0.1, 1.0, 0.95), 0.4, 0.0)
	ship.add_child(heading_marker)


func _rebuild_buoys() -> void:
	for child in buoy_container.get_children():
		child.queue_free()

	for i in range(simulation.red_balls.size()):
		buoy_container.add_child(_create_buoy(
			simulation.red_balls[i], Color(0.95, 0.05, 0.04),
			i == simulation.selected_index and (simulation.move_buoy_pair or simulation.selected_buoy_type == 0)
		))
	for i in range(simulation.green_balls.size()):
		buoy_container.add_child(_create_buoy(
			simulation.green_balls[i], Color(0.05, 0.9, 0.18),
			i == simulation.selected_index and (simulation.move_buoy_pair or simulation.selected_buoy_type == 1)
		))

	_create_box_marker(simulation.red_box, Color(0.8, 0.02, 0.02))
	_create_box_marker(simulation.green_box, Color(0.02, 0.7, 0.08))
	_create_box_marker(simulation.blue_box, Color(0.03, 0.22, 0.95))


func _create_buoy(point: Vector2, color: Color, selected: bool) -> Node3D:
	var root := Node3D.new()
	root.position = navigation_to_3d(point, 0.20)

	var body := MeshInstance3D.new()
	var mesh := CylinderMesh.new()
	mesh.top_radius = 0.20 if not selected else 0.28
	mesh.bottom_radius = mesh.top_radius
	mesh.height = 0.50 if not selected else 0.72
	mesh.radial_segments = 12
	body.mesh = mesh
	body.material_override = _make_material(color, 0.38, 0.05)
	root.add_child(body)

	var cap := MeshInstance3D.new()
	var cap_mesh := SphereMesh.new()
	cap_mesh.radius = mesh.top_radius
	cap_mesh.height = mesh.top_radius * 2.0
	cap.mesh = cap_mesh
	cap.position.y = mesh.height * 0.5
	cap.material_override = body.material_override
	root.add_child(cap)
	return root


func _create_box_marker(point: Vector2, color: Color) -> void:
	var marker := MeshInstance3D.new()
	var mesh := BoxMesh.new()
	mesh.size = Vector3(0.9, 0.12, 0.9)
	marker.mesh = mesh
	marker.position = navigation_to_3d(point, 0.10)
	marker.material_override = _make_material(color, 0.5, 0.1)
	buoy_container.add_child(marker)


func _draw_polyline(target: MeshInstance3D, points: Array[Vector2], color: Color, height: float) -> void:
	if points.size() < 2:
		target.mesh = null
		return
	var line_mesh := ImmediateMesh.new()
	var material := _make_material(color, 1.0, 0.0)
	material.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	line_mesh.surface_begin(Mesh.PRIMITIVE_LINE_STRIP, material)
	for point in points:
		line_mesh.surface_add_vertex(navigation_to_3d(point, height))
	line_mesh.surface_end()
	target.mesh = line_mesh


func _make_material(color: Color, roughness: float, metallic: float) -> StandardMaterial3D:
	var material := StandardMaterial3D.new()
	material.albedo_color = color
	material.roughness = roughness
	material.metallic = metallic
	return material
