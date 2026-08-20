extends Node

## Lightweight MAVLink v1/v2 UDP listener for visualization.
## It reads HEARTBEAT, ATTITUDE, ATTITUDE_QUATERNION and LOCAL_POSITION_NED.
## Transport is receive-only; no command is sent to the vehicle.

@export var simulation_path: NodePath
@export var listen_port := 14550
@export var bind_address := "*"

var simulation: Node
var udp := PacketPeerUDP.new()
var listening := false
var bind_result := OK
var packets_received := 0
var frames_received := 0
var position_updates := 0
var attitude_updates := 0
var last_sender := "-"
var last_message := "Waiting for MAVLink..."
var last_system_id := 0
var last_component_id := 0
var last_position_ned := Vector3.ZERO
var last_yaw_ned := 0.0
var last_quaternion_wxyz := PackedFloat32Array([1.0, 0.0, 0.0, 0.0])
var last_packet_time_msec := -1


func _ready() -> void:
	simulation = get_node(simulation_path)
	bind_result = udp.bind(listen_port, bind_address)
	listening = bind_result == OK
	if not listening:
		last_message = "UDP bind failed: %s" % error_string(bind_result)


func _process(_delta: float) -> void:
	if not listening:
		return
	while udp.get_available_packet_count() > 0:
		var packet := udp.get_packet()
		packets_received += 1
		last_sender = "%s:%d" % [udp.get_packet_ip(), udp.get_packet_port()]
		last_packet_time_msec = Time.get_ticks_msec()
		_parse_datagram(packet)


func _parse_datagram(packet: PackedByteArray) -> void:
	var cursor := 0
	while cursor < packet.size():
		var magic := packet[cursor]
		if magic == 0xFD:
			if cursor + 12 > packet.size():
				return
			var v2_payload_length := packet[cursor + 1]
			var signed_frame := (packet[cursor + 2] & 0x01) != 0
			var v2_frame_length := 10 + v2_payload_length + 2 + (13 if signed_frame else 0)
			if cursor + v2_frame_length > packet.size():
				return
			var system_id := packet[cursor + 5]
			var component_id := packet[cursor + 6]
			var message_id := packet[cursor + 7] | (packet[cursor + 8] << 8) | (packet[cursor + 9] << 16)
			_handle_message(packet, cursor + 10, v2_payload_length, message_id, system_id, component_id)
			cursor += v2_frame_length
		elif magic == 0xFE:
			if cursor + 8 > packet.size():
				return
			var v1_payload_length := packet[cursor + 1]
			var v1_frame_length := 6 + v1_payload_length + 2
			if cursor + v1_frame_length > packet.size():
				return
			_handle_message(packet, cursor + 6, v1_payload_length, packet[cursor + 5], packet[cursor + 3], packet[cursor + 4])
			cursor += v1_frame_length
		else:
			cursor += 1


func _handle_message(packet: PackedByteArray, payload_start: int, payload_length: int, message_id: int, system_id: int, component_id: int) -> void:
	frames_received += 1
	last_system_id = system_id
	last_component_id = component_id

	match message_id:
		0:
			last_message = "HEARTBEAT (0)"
		30:
			if payload_length < 16:
				return
			last_yaw_ned = packet.decode_float(payload_start + 12)
			last_quaternion_wxyz = _yaw_to_quaternion(last_yaw_ned)
			attitude_updates += 1
			last_message = "ATTITUDE (30)"
			simulation.apply_mavlink_yaw(last_yaw_ned)
		31:
			if payload_length < 20:
				return
			var w := packet.decode_float(payload_start + 4)
			var x := packet.decode_float(payload_start + 8)
			var y := packet.decode_float(payload_start + 12)
			var z := packet.decode_float(payload_start + 16)
			last_quaternion_wxyz = PackedFloat32Array([w, x, y, z])
			last_yaw_ned = atan2(2.0 * (w * z + x * y), 1.0 - 2.0 * (y * y + z * z))
			attitude_updates += 1
			last_message = "ATTITUDE_QUATERNION (31)"
			simulation.apply_mavlink_yaw(last_yaw_ned)
		32:
			if payload_length < 28:
				return
			last_position_ned = Vector3(
				packet.decode_float(payload_start + 4),
				packet.decode_float(payload_start + 8),
				packet.decode_float(payload_start + 12)
			)
			position_updates += 1
			last_message = "LOCAL_POSITION_NED (32)"
			simulation.apply_mavlink_position_ned(last_position_ned)
		_:
			last_message = "MAVLink message %d" % message_id


func _yaw_to_quaternion(yaw: float) -> PackedFloat32Array:
	return PackedFloat32Array([cos(yaw * 0.5), 0.0, 0.0, sin(yaw * 0.5)])


func get_listener_status() -> String:
	if not listening:
		return "ERROR: %s" % error_string(bind_result)
	return "LISTENING UDP :%d" % listen_port


func get_packet_age_text() -> String:
	if last_packet_time_msec < 0:
		return "never"
	return "%.2f s" % (float(Time.get_ticks_msec() - last_packet_time_msec) / 1000.0)
