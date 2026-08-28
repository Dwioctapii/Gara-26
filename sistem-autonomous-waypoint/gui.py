from __future__ import annotations
"""Definisi arena dan antarmuka dashboard Matplotlib untuk sistem autonomous waypoint."""

import math
from dataclasses import dataclass
from pathlib import Path

import cv2
import matplotlib.animation as animation
import matplotlib.gridspec as gridspec
import matplotlib.pyplot as plt
import matplotlib.transforms as transforms
import numpy as np
from matplotlib.widgets import Button

def mirror_elements(elements: list[tuple[float, float]]) -> list[tuple[float, float]]:
    return [(-x, y) for x, y in elements]

def mirror_squares(squares: list[dict]) -> list[dict]:
    return [
        {"pos": (-item["pos"][0], item["pos"][1]), "color": item["color"], "id": item["id"]}
        for item in squares
    ]

def load_waypoints(path: Path) -> list[tuple[float, float]]:
    if not path.exists():
        return []
    waypoints = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            x_value, y_value = map(float, line.split(","))
            waypoints.append((x_value, y_value))
    return waypoints

@dataclass
class Arena:
    current: str
    red_balls: dict[str, list[tuple[float, float]]]
    green_balls: dict[str, list[tuple[float, float]]]
    blue_balls: dict[str, list[tuple[float, float]]]
    squares: dict[str, list[dict]]
    waypoints: dict[str, list[tuple[float, float]]]

    @property
    def active_red_square(self) -> tuple[float, float]:
        return self.squares[self.current][0]["pos"]

    def switch(self) -> str:
        self.current = "B" if self.current == "A" else "A"
        return self.current

    def gps_to_xy(self, lat: float, lon: float, heading_offset: float, state) -> tuple[float, float]:
        if getattr(state, 'lat0', None) is None:
            state.lat0, state.lon0 = lat, lon
        dx_east = (lon - state.lon0) * 111320.0 * math.cos(math.radians(state.lat0))
        dy_north = (lat - state.lat0) * 111320.0
        x_local = dx_east * math.cos(heading_offset) - dy_north * math.sin(heading_offset)
        y_local = dx_east * math.sin(heading_offset) + dy_north * math.cos(heading_offset)
        if self.current == "B":
            x_local = -x_local
        origin_x, origin_y = self.active_red_square
        return origin_x + x_local, origin_y + y_local

def build_arena(waypoint_file: Path) -> Arena:
    red_a = [(-4, 13), (-5, 16), (-4, 19), (-10, 28), (-13, 28), (-16, 28), (-19, 28), (-27, 19), (-28, 16), (-28, 13)]
    green_a = [(-2, 13), (-3, 16), (-2, 19), (-10, 26), (-13, 26), (-16, 26), (-19, 26), (-25, 19), (-26, 16), (-26, 13)]
    blue_a = [(-4, 1.7), (-4, 2.4), (-4, 3.1)]
    squares_a = [
        {"pos": (-3, 2), "color": "#ff1744", "id": 100},
        {"pos": (-22, 4), "color": "#00c853", "id": 101},
        {"pos": (-25, 8), "color": "#2979ff", "id": 102},
    ]
    waypoints_a = load_waypoints(waypoint_file)
    return Arena(
        current="A",
        red_balls={"A": red_a, "B": mirror_elements(red_a)},
        green_balls={"A": green_a, "B": mirror_elements(green_a)},
        blue_balls={"A": blue_a, "B": mirror_elements(blue_a)},
        squares={"A": squares_a, "B": mirror_squares(squares_a)},
        waypoints={"A": waypoints_a, "B": mirror_elements(waypoints_a)},
    )

class Dashboard:
    def __init__(self, state, arena, mavlink, reset_capture):
        self.state, self.arena, self.mavlink, self.reset_capture = state, arena, mavlink, reset_capture
        self.arrow = None
        self.arena_patches = []
        self._build()

    def _build(self):
        plt.style.use("dark_background")
        self.fig = plt.figure(figsize=(14.5, 8.2), facecolor="#121212")
        grid = gridspec.GridSpec(2, 2, width_ratios=[1.3, 1.5], figure=self.fig)
        self.ax = self.fig.add_subplot(grid[:, 0]); self.ax.set_facecolor("#1e1e1e"); self.ax.set_aspect("equal")
        self.ax_cam = self.fig.add_subplot(grid[0, 1]); self.ax_cam.set_facecolor("#000000"); self.ax_cam.axis("off")
        self.ax_cam.set_title("LIVE CAMERA & YOLO DETECT", fontsize=10, fontweight="bold", color="#00d2ff", pad=8)
        self.cam_im = self.ax_cam.imshow(self.state.latest_frame_rgb)
        self._build_telemetry(grid)
        self.robot, = self.ax.plot([], [], "o", markersize=8, color="#00e5ff", zorder=5)
        self.trace, = self.ax.plot([], [], linewidth=2, color="#00b0ff", zorder=4)
        self.wp_line, = self.ax.plot([], [], color="#ffea00", linestyle="--", linewidth=1.2, alpha=.7, zorder=2)
        self.wp_points = self.ax.scatter([], [], color="#ffea00", s=15, zorder=3)
        self.render_arena()
        self._build_buttons()
        plt.subplots_adjust(bottom=.10, left=.06, right=.96, top=.93, wspace=.25, hspace=.28)

    def _build_telemetry(self, grid):
        dash = self.fig.add_subplot(grid[1, 1]); dash.set_facecolor("#1a1a1a"); dash.set(xlim=(0, 1), ylim=(0, 1)); dash.axis("off")
        dash.set_title("SYSTEM TELEMETRY & VISION STATUS", fontsize=10, fontweight="bold", color="#00d2ff", pad=8)
        labels = "ACTIVE ARENA\nWEBSOCKET STATUS\nHTTP PHOTO SERVER\nYOLO DETECTION\nFLIGHT MODE\nARMING STATE\nGPS STATUS\nGPS LAT / LON\nPOSISI ARENA (X / Y)\nSPEED OVER GROUND (SOG)\nCOURSE OVER GROUND (COG)\nHEADING (EARTH)"
        dash.text(.03, .5, labels, color="#888888", fontsize=8.5, family="monospace", va="center", linespacing=1.25)
        self.values = dash.text(.97, .5, "...", color="#00e676", fontsize=8.5, family="monospace", va="center", ha="right", linespacing=1.25, weight="bold")

    def render_arena(self):
        for patch in self.arena_patches: patch.remove()
        self.arena_patches.clear(); name = self.arena.current
        self.ax.set(xlim=(-30, 0) if name == "A" else (0, 30), ylim=(0, 30)); self.ax.set_xticks(range(-30 if name == "A" else 0, 1 if name == "A" else 31, 5)); self.ax.set_yticks(range(0, 31, 5))
        self.ax.grid(True, linestyle="--", color="#333333", alpha=.7); self.ax.set_xlabel("X (Meter)"); self.ax.set_ylabel("Y (Meter)")
        self.ax.set_title(f"ARENA {name} ({'ORIGINAL' if name == 'A' else 'MIRRORED'})", color="#00d2ff" if name == "A" else "#ff007f", weight="bold")
        for points, color, radius in ((self.arena.red_balls[name], "#ff4444", .35), (self.arena.green_balls[name], "#00e676", .35), (self.arena.blue_balls[name], "#00d2ff", .25)):
            self.arena_patches.extend(self.ax.add_patch(plt.Circle(point, radius, color=color, alpha=.8)) for point in points)
        for square in self.arena.squares[name]:
            x, y = square["pos"]; self.arena_patches.append(self.ax.add_patch(plt.Rectangle((x-.5, y-.5), 1, 1, color=square["color"])))
        waypoints = self.arena.waypoints[name]
        if waypoints:
            x, y = zip(*waypoints); self.wp_line.set_data(x, y); self.wp_points.set_offsets(np.c_[x, y])

    def _build_buttons(self):
        self.btn_arena = Button(self.fig.add_axes([.42, .03, .18, .045]), "SWITCH TO ARENA B", color="#212121", hovercolor="#37474f")
        self.btn_arena.on_clicked(self.switch_arena)
        self.btn_reset = Button(self.fig.add_axes([.62, .03, .18, .045]), "RESET FOTO (RE-CAPTURE)", color="#212121", hovercolor="#b71c1c")
        self.btn_reset.on_clicked(lambda _: self.reset_capture())

    def switch_arena(self, _):
        self.arena.switch(); self.state.reset_tracking()
        if self.arrow: self.arrow.remove(); self.arrow = None
        self.btn_arena.label.set_text("SWITCH TO ARENA A" if self.arena.current == "B" else "SWITCH TO ARENA B")
        self.render_arena(); self.fig.canvas.draw_idle()

    def update(self, _):
        self.mavlink.poll(); self.cam_im.set_data(self.state.latest_frame_rgb)
        if self.state.current_x is not None:
            self.robot.set_data([self.state.current_x], [self.state.current_y]); self.trace.set_data(self.state.trace_x, self.state.trace_y)
            if self.arrow: self.arrow.remove()
            yaw = -self.state.current_yaw_rad if self.arena.current == "B" else self.state.current_yaw_rad; color = "#00e5ff" if self.arena.current == "A" else "#ff007f"
            self.arrow = self.ax.arrow(self.state.current_x, self.state.current_y, 1.2*math.sin(yaw), 1.2*math.cos(yaw), head_width=.4, head_length=.5, fc=color, ec=color)
        fix = {0:"NO GPS", 1:"NO FIX", 2:"2D FIX", 3:"3D FIX", 4:"DGPS", 5:"RTK FLT", 6:"RTK FIX"}.get(self.state.gps_fix_type, "UNKNOWN")
        position = f"{self.state.current_x:.2f} m, {self.state.current_y:.2f} m" if self.state.current_x is not None else "0.00 m, 0.00 m"
        values = [f"ARENA {self.arena.current}", self.state.ws_last_status, "PORT 8766 (ACTIVE)", self.state.last_detected_class, self.state.current_mode, "ARMED" if self.state.is_armed else "DISARMED", f"{fix} ({self.state.satellites_visible} Sats)", f"{self.state.current_lat:.6f}°, {self.state.current_lon:.6f}°", position, f"{self.state.current_sog:.2f} Knots", f"{self.state.current_cog:.1f}°", f"{math.degrees(self.state.raw_yaw_rad)%360:.1f}°"]
        self.values.set_text("\n".join(": " + value for value in values)); self.values.set_color("#00e676" if self.state.is_armed else "#ff5252")
        return self.robot, self.trace, self.cam_im, self.values

    def show(self):
        # Simpan referensi agar Python tidak menghapus animasi sebelum event loop GUI berjalan.
        self.animation = animation.FuncAnimation(
            self.fig,
            self.update,
            interval=30,
            blit=False,
            cache_frame_data=False,
        )
        plt.show()

# === ADAPTER UNTUK INTEGRASI DENGAN BACKEND SAAT INI ===

class GUIStateAdapter:
    def __init__(self, store, photo_dir):
        self.store = store
        self.photo_dir = Path(photo_dir)
        self.lat0 = None
        self.lon0 = None
        self.yaw_offset = None
        self.trace_x = []
        self.trace_y = []
        self.arena_ref = None
        
        # Placeholder untuk frame kamera jika tidak ada foto
        self._blank_frame = np.zeros((240, 320, 3), dtype=np.uint8)
        
    def reset_tracking(self):
        self.trace_x.clear()
        self.trace_y.clear()
        self.lat0 = None
        self.lon0 = None
        self.yaw_offset = None

    @property
    def latest_frame_rgb(self):
        # Membaca live frame langsung dari memori yang disimpan oleh vision_worker
        if hasattr(self.store, 'live_frame_bgr') and self.store.live_frame_bgr is not None:
            return cv2.cvtColor(self.store.live_frame_bgr, cv2.COLOR_BGR2RGB)
        
        # Jika belum ada live frame, fallback ke foto terakhir (jika ada)
        try:
            atas_path = self.photo_dir / "atas.jpg"
            if atas_path.exists():
                img = cv2.imread(str(atas_path))
                if img is not None:
                    return cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        except Exception:
            pass
        return self._blank_frame

    @property
    def raw_yaw_rad(self):
        snap = self.store.snapshot()
        return snap.get("orientation", {}).get("z", 0.0)

    @property
    def current_yaw_rad(self):
        raw = self.raw_yaw_rad
        if self.yaw_offset is None:
            # Inisialisasi yaw_offset pertama kali saat ada data orientasi masuk
            if self.store.snapshot().get("connected"):
                self.yaw_offset = raw
            else:
                return 0.0
        rel_yaw = raw - self.yaw_offset
        return math.atan2(math.sin(rel_yaw), math.cos(rel_yaw))

    @property
    def current_lat(self):
        return self.store.snapshot().get("gps", {}).get("lat") or 0.0

    @property
    def current_lon(self):
        return self.store.snapshot().get("gps", {}).get("lon") or 0.0

    @property
    def current_x(self):
        lat, lon = self.current_lat, self.current_lon
        if lat != 0.0 and lon != 0.0 and self.arena_ref:
            y_off = self.yaw_offset if self.yaw_offset is not None else 0.0
            x, y = self.arena_ref.gps_to_xy(lat, lon, y_off, self)
            if not self.trace_x or (math.hypot(x - self.trace_x[-1], y - self.trace_y[-1]) > 0.05):
                self.trace_x.append(x)
                self.trace_y.append(y)
            return x
        return None

    @property
    def current_y(self):
        lat, lon = self.current_lat, self.current_lon
        if lat != 0.0 and lon != 0.0 and self.arena_ref:
            y_off = self.yaw_offset if self.yaw_offset is not None else 0.0
            x, y = self.arena_ref.gps_to_xy(lat, lon, y_off, self)
            return y
        return None

    @property
    def gps_fix_type(self):
        return 3 if self.store.snapshot().get("gps", {}).get("fix") else 1

    @property
    def satellites_visible(self):
        return self.store.snapshot().get("gps", {}).get("satellites", 0)

    @property
    def current_sog(self):
        return self.store.snapshot().get("gps", {}).get("sog", 0.0) * 1.94384

    @property
    def current_cog(self):
        return self.store.snapshot().get("gps", {}).get("cog", 0.0)

    @property
    def ws_last_status(self):
        return "CONNECTED" if self.store.snapshot().get("connected") else "DISCONNECTED"

    @property
    def last_detected_class(self):
        return self.store.snapshot().get("detection", {}).get("label", "STANDBY")

    @property
    def current_mode(self):
        return self.store.snapshot().get("mode", "UNKNOWN")

    @property
    def is_armed(self):
        return self.store.snapshot().get("arm", "Disarmed") == "Armed"

class MavlinkDummyAdapter:
    def poll(self):
        pass

def run_dashboard(store, photo_dir):
    # Buat arena dengan file kosong jika tidak ada
    wp_path = Path("waypoints.txt")
    if not wp_path.exists():
        wp_path.write_text("")
        
    arena = build_arena(wp_path)
    state_adapter = GUIStateAdapter(store, photo_dir)
    state_adapter.arena_ref = arena
    
    def reset_capture():
        store.update({"detection": {"label": "STANDBY", "foto_atas_ready": False, "foto_bawah_ready": False}})
        # Hapus foto jika ada
        try:
            (Path(photo_dir) / "atas.jpg").unlink(missing_ok=True)
            (Path(photo_dir) / "bawah.jpg").unlink(missing_ok=True)
        except Exception:
            pass

    dashboard = Dashboard(state_adapter, arena, MavlinkDummyAdapter(), reset_capture)
    dashboard.show()
