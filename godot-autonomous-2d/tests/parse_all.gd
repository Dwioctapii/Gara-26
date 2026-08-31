extends SceneTree

const Config = preload("res://scripts/core/asv_config.gd")
const MavlinkCoordinates = preload("res://scripts/core/mavlink_coordinates.gd")
const SimulationInput = preload("res://scripts/input/simulation_input.gd")
const PathPlanner = preload("res://scripts/path_planner.gd")
const CoursePlanner = preload("res://scripts/planning/course_planner.gd")
const GridAStar = preload("res://scripts/planning/grid_astar.gd")
const MapRenderer = preload("res://scripts/ui/map_renderer.gd")
const StatusHud = preload("res://scripts/ui/status_hud.gd")
const SmokeTest = preload("res://tests/smoke_test.gd")


func _init() -> void:
	quit()
