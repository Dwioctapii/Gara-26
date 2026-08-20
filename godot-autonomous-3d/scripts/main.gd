extends Node

@onready var simulation: Node = $Simulation
@onready var mavlink: Node = $MavlinkListener
@onready var status_label: Label = $UI/Status
@onready var mavlink_debug_label: Label = $UI/MavlinkDebug
@onready var selection_overlay: ColorRect = $UI/SelectionOverlay
@onready var mode_notice: Label = $UI/ModeNotice


func _input(event: InputEvent) -> void:
	if not event is InputEventKey or not event.pressed or event.echo:
		return
	if event.keycode == KEY_T:
		simulation.start_demo()
		get_viewport().set_input_as_handled()
	elif event.keycode == KEY_B:
		simulation.start_real()
		get_viewport().set_input_as_handled()


func _process(_delta: float) -> void:
	selection_overlay.visible = simulation.is_select_mode()
	if simulation.is_select_mode():
		mode_notice.text = "WAITING — PRESS T OR B"
	elif simulation.is_real_mode():
		if mavlink.position_updates == 0:
			mode_notice.text = "REAL MODE — WAITING FOR LOCAL_POSITION_NED ON UDP :14550"
		else:
			mode_notice.text = "REAL MODE — MAVLINK LIVE — packet age %s" % mavlink.get_packet_age_text()
	else:
		mode_notice.text = "DEMO MODE — AUTONOMOUS SIMULATION RUNNING"

	var q: PackedFloat32Array = simulation.get_mavlink_yaw_quaternion()
	var ned: Vector3 = simulation.map_to_mavlink_ned(simulation.ship_position)
	var mode := "PAIR RED + GREEN" if simulation.move_buoy_pair else ("SINGLE RED" if simulation.selected_buoy_type == 0 else "SINGLE GREEN")
	var state := "WAITING FOR T/B" if simulation.is_select_mode() else ("MISSION COMPLETE" if simulation.mission_complete else ("PAUSED" if simulation.is_paused else ("WAITING MAVLINK" if simulation.is_real_mode() and mavlink.position_updates == 0 else "RUNNING")))

	status_label.text = (
		"PLAY: %s\n" % simulation.get_play_mode_name()
		+ "STATE: %s\n" % state
		+ "Mode: %s   Selected: #%d\n\n" % [mode, simulation.selected_index + 1]
		+ "PLANNER (East / North)\n"
		+ "E: %7.2f m   N: %7.2f m\n" % [simulation.ship_position.x, simulation.ship_position.y]
		+ "Heading: %7.2f deg\n\n" % rad_to_deg(simulation.ship_heading)
		+ "MAVLink LOCAL_NED\n"
		+ "N: %7.2f   E: %7.2f   D: %5.2f\n" % [ned.x, ned.y, ned.z]
		+ "Yaw NED: %7.2f deg\n" % rad_to_deg(simulation.map_heading_to_mav_yaw(simulation.ship_heading))
		+ "Quaternion (w x y z)\n"
		+ "%.4f  %.4f  %.4f  %.4f\n\n" % [q[0], q[1], q[2], q[3]]
		+ "WP: %d / %d   Path point: %d / %d"
		% [
			mini(simulation.current_wp_index + 1, simulation.mission_waypoints.size()),
			simulation.mission_waypoints.size(),
			mini(simulation.current_path_index + 1, simulation.current_path.size()),
			simulation.current_path.size()
		]
	)

	var selected := clampi(simulation.selected_index, 0, mini(simulation.red_balls.size(), simulation.green_balls.size()) - 1)
	var red: Vector2 = simulation.red_balls[selected]
	var green: Vector2 = simulation.green_balls[selected]
	var gate := (red + green) * 0.5
	var listener_q: PackedFloat32Array = mavlink.last_quaternion_wxyz

	mavlink_debug_label.text = (
		"MAVLINK DEBUG — RECEIVE ONLY\n"
		+ "%s\n" % mavlink.get_listener_status()
		+ "Mode input: %s\n" % ("APPLY TO SHIP" if simulation.is_real_mode() else "MONITOR ONLY (DEMO active)")
		+ "Sender: %s\n" % mavlink.last_sender
		+ "Last: %s   age: %s\n" % [mavlink.last_message, mavlink.get_packet_age_text()]
		+ "sys/comp: %d/%d   UDP packets: %d   frames: %d\n" % [mavlink.last_system_id, mavlink.last_component_id, mavlink.packets_received, mavlink.frames_received]
		+ "Position updates: %d   attitude updates: %d\n\n" % [mavlink.position_updates, mavlink.attitude_updates]
		+ "LISTENED POSITION — LOCAL NED\n"
		+ "N: %8.3f   E: %8.3f   D: %8.3f\n" % [mavlink.last_position_ned.x, mavlink.last_position_ned.y, mavlink.last_position_ned.z]
		+ "Yaw: %8.3f deg\n" % rad_to_deg(mavlink.last_yaw_ned)
		+ "q(wxyz): %.4f %.4f %.4f %.4f\n\n" % [listener_q[0], listener_q[1], listener_q[2], listener_q[3]]
		+ "SELECTED BUOY #%d — East/North\n" % (selected + 1)
		+ "RED:   E %7.2f   N %7.2f\n" % [red.x, red.y]
		+ "GREEN: E %7.2f   N %7.2f\n" % [green.x, green.y]
		+ "GATE:  E %7.2f   N %7.2f"
		% [gate.x, gate.y]
	)
