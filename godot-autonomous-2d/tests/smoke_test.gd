extends Node

## Uji cepat untuk kontrak utama simulasi. Jalankan dengan:
## godot --headless --path . --scene res://tests/smoke_test.tscn

var _failures: Array[String] = []


func _ready() -> void:
	_run.call_deferred()


func _run() -> void:
	var main_scene: PackedScene = load("res://scenes/main.tscn")
	var simulation := main_scene.instantiate()
	add_child(simulation)

	# _ready() berjalan ketika node masuk tree; satu frame tambahan memberi HUD
	# dan renderer kesempatan menerima snapshot state pertama.
	await get_tree().process_frame
	simulation.toggle_pause()

	_check(not simulation.current_path.is_empty(), "Rute awal harus terbentuk.")
	_check(simulation.get_gate_centers().size() == 10, "Course harus memiliki 10 gate.")

	var ship_before: Vector2 = simulation.ship_position
	var red_before: Vector2 = simulation.red_buoys[0]
	var green_before: Vector2 = simulation.green_buoys[0]
	var offset := Vector2(0.5, 0.0)
	simulation.move_selected_buoy(offset)

	_check(
		simulation.ship_position.is_equal_approx(ship_before),
		"Live replan tidak boleh memindahkan kapal.",
	)
	_check(
		simulation.red_buoys[0].is_equal_approx(red_before + offset),
		"Buoy merah terpilih harus berpindah.",
	)
	_check(
		simulation.green_buoys[0].is_equal_approx(green_before + offset),
		"Mode pair harus memindahkan buoy hijau pasangannya.",
	)
	_check(not simulation.current_path.is_empty(), "Rute hasil live replan harus terbentuk.")

	var ned: Vector3 = simulation.map_to_mavlink_ned(Vector2(3.0, 4.0), 2.0)
	_check(
		ned.is_equal_approx(Vector3(4.0, 3.0, -2.0)),
		"Konversi planner ke MAVLink LOCAL_NED berubah.",
	)

	if _failures.is_empty():
		print("SMOKE TEST PASSED: route, live replan, dan MAVLink valid.")
		get_tree().quit(0)
	else:
		for failure: String in _failures:
			push_error(failure)
		get_tree().quit(1)


func _check(condition: bool, message: String) -> void:
	if not condition:
		_failures.append(message)
