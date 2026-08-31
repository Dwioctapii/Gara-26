extends RefCounted

## Satu sumber konfigurasi untuk simulasi ASV 2D.
##
## Nilai di sini dikelompokkan berdasarkan maknanya supaya perubahan ukuran kapal,
## toleransi navigasi, atau bentuk lintasan tidak tersebar di banyak script.


# --- Dimensi fisik ---------------------------------------------------------

const SHIP_LENGTH: float = 1.04
const SHIP_WIDTH: float = 0.52
const BUOY_RADIUS: float = 0.15
const NAVIGATION_MARGIN: float = 0.30

## Setengah lebar minimum gate yang masih menyisakan margin di kedua sisi kapal.
const GATE_REQUIRED_HALF_WIDTH: float = (
	SHIP_WIDTH * 0.5 + BUOY_RADIUS + NAVIGATION_MARGIN
)


# --- Posisi course ---------------------------------------------------------

const RED_BOX := Vector2(20.5, 0.0)
const GREEN_BOX := Vector2(5.5, 1.0)
const BLUE_BOX := Vector2(2.5, 4.0)

## Array dibuat lewat fungsi agar setiap pemanggil memperoleh salinan yang aman
## untuk dipindahkan saat simulasi berjalan.
static func default_red_buoys() -> Array[Vector2]:
	return [
		Vector2(20.0, 7.0),
		Vector2(18.7, 10.0),
		Vector2(20.5, 12.6),
		Vector2(14.5, 18.5),
		Vector2(12.5, 18.5),
		Vector2(10.5, 18.5),
		Vector2(8.5, 18.5),
		Vector2(1.5, 15.0),
		Vector2(0.0, 11.5),
		Vector2(0.0, 7.5),
	]


static func default_green_buoys() -> Array[Vector2]:
	return [
		Vector2(21.5, 7.0),
		Vector2(20.2, 10.0),
		Vector2(22.1, 12.6),
		Vector2(14.5, 20.0),
		Vector2(12.5, 20.0),
		Vector2(10.5, 20.0),
		Vector2(8.5, 20.0),
		Vector2(3.0, 15.0),
		Vector2(1.3, 11.5),
		Vector2(1.3, 7.5),
	]


static func decorative_buoys() -> Array[Vector2]:
	return [
		RED_BOX + Vector2(-0.7, 1.0),
		RED_BOX + Vector2(0.0, 1.0),
		RED_BOX + Vector2(0.7, 1.0),
	]


# --- Perencanaan rute ------------------------------------------------------

const MAP_SIZE: float = 35.0
const GRID_RESOLUTION: float = 0.5

## Jarak ini sengaja lebih kecil daripada margin eksperimen lama 1,5 m.
## Margin 1,5 m menutup titik tengah gate dan membuat jalur berputar balik.
const COURSE_OBSTACLE_MARGIN: float = 0.58

const CURVE_SAMPLE_COUNT: int = 60
const SPLINE_SAMPLE_COUNT: int = 20

## Indeks berikut merujuk ke daftar waypoint misi, bukan indeks array buoy.
## Course memiliki bentuk khusus pada beberapa kaki sehingga tidak semuanya
## boleh diganti dengan rute A* generik.
const BEZIER_GATE_3_TO_4_TARGET: int = 4
const LINEAR_GATE_START_TARGET: int = 5
const LINEAR_GATE_END_TARGET: int = 7
const SAFE_GATE_8_TARGET: int = 8
const SAFE_GATE_9_TARGET: int = 9
const SMOOTH_TAIL_TARGET: int = 10


# --- Simulasi dan tampilan -------------------------------------------------

const SHIP_SPEED: float = 2.0
const WAYPOINT_RADIUS: float = 1.0
const PATH_POINT_RADIUS: float = 0.25
const TRAIL_RECORD_DISTANCE: float = 0.12
const BUOY_MOVE_STEP: float = 0.5

const HUD_WIDTH: float = 350.0
const VIEW_PADDING: float = 35.0
const WORLD_PADDING_METERS: float = 1.5
const MIN_DRAW_SCALE: float = 3.0
const MAX_DRAW_SCALE: float = 40.0
