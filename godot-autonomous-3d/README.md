# ASV MAVLink Trajectory Demo — Godot 4.5.1

Open `project.godot` with Godot 4.5.1, then press **F6** or **F5**.
At boot the simulator waits on the mode-selection screen; press `T` or `B`.

The navigation planner operates on a flat East/North map. The same state drives a
simple 3D vessel and a 2D trajectory map. `navigation_simulation.gd` includes the
coordinate and yaw/quaternion conversion helpers intended for a future MAVLink
transport layer.

## Controls

- T: demo mode; the vessel autonomously follows the planned path
- B: real mode; internal motion stops and MAVLink UDP data drives the vessel
- W/A/S/D: move selected buoy or buoy pair
- Left/Right: change selected buoy
- Tab: pair/single mode
- Q: red/green selection in single mode
- Space: add random buoy noise and replan
- R: reset buoys
- P: pause/resume
- C: toggle overview/follow camera

## Display colours

- Yellow: current planned trajectory
- Red: track already travelled by the vessel

The gate-3 to gate-4 transition preserves the quadratic Bezier course from the
original planner. Designed Bezier/linear course legs are excluded from path
simplification so they cannot collapse into a diagonal shortcut.

The gate 7 -> 8 and gate 8 -> 9 transitions use matched cubic Bezier tangents.
They cross the horizontal gates through their midpoints, avoid a hard turn at
gate 8, and maintain at least 0.65 m centre clearance from the nearby buoys.
The remaining course after gate 9 continues as a Catmull-Rom spline.

## Real/MAVLink mode

The project listens on UDP port `14550`. It accepts MAVLink v1/v2 frames and
visualizes `LOCAL_POSITION_NED`, `ATTITUDE`, and `ATTITUDE_QUATERNION`. The
listener is receive-only and does not arm or command the vehicle.

In real mode the vessel intentionally remains stationary until at least one
`LOCAL_POSITION_NED` message is received. The top banner says whether it is
waiting or receiving live packets. Press `T` at any time to return to demo.

## Coordinate conventions

- Planner: `Vector2(East, North)`
- Godot 3D: `Vector3(East, Up, -North)`
- MAVLink local NED: `Vector3(North, East, Down)`
- MAVLink quaternion array: `(w, x, y, z)`
- Godot `Quaternion` constructor: `(x, y, z, w)`
