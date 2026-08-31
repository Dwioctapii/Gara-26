extends Node

## Menerjemahkan tombol keyboard menjadi perintah yang bermakna bagi simulasi.
## Script ini tidak mengubah array buoy secara langsung; semua perubahan tetap
## melewati API path_planner.gd agar replanning dan pembaruan tampilan konsisten.

const Config = preload("res://scripts/core/asv_config.gd")

var _simulation


func bind(simulation) -> void:
	_simulation = simulation


func _input(event: InputEvent) -> void:
	if _simulation == null or not event is InputEventKey:
		return

	var key_event := event as InputEventKey
	if not key_event.pressed or key_event.echo:
		return

	match key_event.keycode:
		KEY_SPACE:
			_simulation.add_noise_to_buoys()
		KEY_R:
			_simulation.reset_buoys()
		KEY_P:
			_simulation.toggle_pause()
		KEY_TAB:
			_simulation.toggle_buoy_move_mode()
		KEY_Q:
			_simulation.toggle_selected_buoy_color()
		KEY_LEFT:
			_simulation.select_previous_buoy()
		KEY_RIGHT:
			_simulation.select_next_buoy()
		_:
			var movement := _movement_for_key(key_event.keycode)
			if movement != Vector2.ZERO:
				_simulation.move_selected_buoy(movement)


func _movement_for_key(keycode: Key) -> Vector2:
	match keycode:
		KEY_W:
			return Vector2(0.0, Config.BUOY_MOVE_STEP)
		KEY_S:
			return Vector2(0.0, -Config.BUOY_MOVE_STEP)
		KEY_A:
			return Vector2.LEFT * Config.BUOY_MOVE_STEP
		KEY_D:
			return Vector2.RIGHT * Config.BUOY_MOVE_STEP
		_:
			return Vector2.ZERO
