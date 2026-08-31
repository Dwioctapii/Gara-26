extends PanelContainer

## HUD hanya menyajikan snapshot state dari simulasi.
## Tidak ada perhitungan lintasan atau perubahan model di sini, sehingga desain
## panel dapat diganti tanpa risiko mengubah perilaku kapal.

@onready var _status_label: Label = %StatusLabel

var _simulation


func bind(simulation) -> void:
	_simulation = simulation
	refresh()


func refresh() -> void:
	if _simulation == null or not is_node_ready():
		return
	_status_label.text = _build_status_text(_simulation.get_status_snapshot())


func _build_status_text(status: Dictionary) -> String:
	var state_text := "RUNNING"
	if status["mission_complete"]:
		state_text = "MISSION COMPLETE"
	elif status["is_paused"]:
		state_text = "PAUSED"

	var buoy_mode := "PAIR RED + GREEN"
	if not status["move_buoy_pair"]:
		buoy_mode = (
			"SINGLE RED"
			if status["selected_buoy_type"] == 0
			else "SINGLE GREEN"
		)

	var position: Vector2 = status["ship_position"]
	var waypoint_number: int = mini(
		status["current_wp_index"] + 1,
		status["waypoint_count"],
	)
	var path_number: int = mini(
		status["current_path_index"] + 1,
		status["path_point_count"],
	)

	return "\n".join(PackedStringArray([
		"ASV COURSE PLANNER",
		"Godot 4.5",
		"",
		"SHIP",
		"Size: 1.04 x 0.52 m",
		"X: %.2f m" % position.x,
		"Y: %.2f m" % position.y,
		"Heading: %.1f deg" % rad_to_deg(status["ship_heading"]),
		"Speed: %.2f m/s" % status["ship_speed"],
		"",
		"STATE",
		state_text,
		"WP: %d / %d" % [waypoint_number, status["waypoint_count"]],
		"Path: %d / %d" % [path_number, status["path_point_count"]],
		"",
		"BUOY",
		buoy_mode,
		"Selected: #%d" % (status["selected_buoy_index"] + 1),
		"Gate width: %.2f m" % status["selected_gate_width"],
		"Recommended minimum: %.2f m" % status["required_gate_width"],
		"",
		"PLANNER",
		"A* + Bezier + Catmull-Rom",
		"Obstacle margin: %.2f m" % status["obstacle_margin"],
		"Live replanning: ON",
		"Yellow: planned path",
		"Red: traveled trail",
		"",
		"CONTROL",
		"WASD: Move buoy",
		"LEFT/RIGHT: Select",
		"TAB: Pair/Single",
		"Q: Red/Green",
		"SPACE: Add noise",
		"R: Reset buoy",
		"P: Pause",
	]))
