"""Komponen 2: tombol Arena A/B, form PID, dan status data Pixhawk."""

import math
import tkinter as tk
from tkinter import ttk

from .websocket import GUIWebSocket


class ControlsWindow:
    def __init__(self, root, websocket):
        self.root = root
        self.ws = websocket
        self.pid_version = None
        self.entries = {}

        # ── Outer container ──────────────────────────────────────────
        outer = ttk.Frame(root)
        outer.pack(fill="both", expand=True)

        # Canvas + Scrollbar vertikal
        canvas = tk.Canvas(outer, highlightthickness=0)
        scrollbar = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        # Frame dalam canvas — semua widget masuk sini
        frame = ttk.Frame(canvas, padding=12)
        frame_id = canvas.create_window((0, 0), window=frame, anchor="nw")

        # Sesuaikan scroll region setiap kali ukuran frame berubah
        def _on_frame_configure(_event):
            canvas.configure(scrollregion=canvas.bbox("all"))

        # Lebarkan inner frame mengikuti lebar canvas
        def _on_canvas_resize(event):
            canvas.itemconfig(frame_id, width=event.width)

        frame.bind("<Configure>", _on_frame_configure)
        canvas.bind("<Configure>", _on_canvas_resize)

        # Scroll dengan mouse wheel (Linux: Button-4/5, Windows/Mac: MouseWheel)
        def _on_mousewheel(event):
            if event.num == 4:
                canvas.yview_scroll(-1, "units")
            elif event.num == 5:
                canvas.yview_scroll(1, "units")
            else:
                canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        canvas.bind_all("<MouseWheel>", _on_mousewheel)
        canvas.bind_all("<Button-4>", _on_mousewheel)
        canvas.bind_all("<Button-5>", _on_mousewheel)

        # ── Konten ───────────────────────────────────────────────────
        ttk.Label(frame, text="ASV CONTROL", font=("Segoe UI", 18, "bold")).pack(anchor="w")
        self.status = ttk.Label(frame, text="CONNECTING")
        self.status.pack(anchor="w", pady=(0, 6))

        # --- Pilih Arena ---
        tracks = ttk.LabelFrame(frame, text="Pilih Arena", padding=8)
        tracks.pack(fill="x", pady=(0, 8))
        ttk.Button(tracks, text="ARENA A", command=lambda: self.ws.command("set_track", track="A")).pack(side="left", expand=True, fill="x")
        ttk.Button(tracks, text="ARENA B", command=lambda: self.ws.command("set_track", track="B")).pack(side="left", expand=True, fill="x", padx=(8, 0))

        # --- Form PID ---
        pid = ttk.LabelFrame(frame, text="Set PID", padding=8)
        pid.pack(fill="x", pady=(0, 8))
        for row, key in enumerate(("kp", "ki", "kd", "deadband", "integral_limit")):
            ttk.Label(pid, text=key).grid(row=row, column=0, sticky="w")
            entry = ttk.Entry(pid)
            entry.grid(row=row, column=1, sticky="ew", padx=(8, 0), pady=2)
            self.entries[key] = entry
        pid.columnconfigure(1, weight=1)
        ttk.Button(pid, text="SIMPAN PID", command=self.save_pid).grid(
            row=5, column=0, columnspan=2, sticky="ew", pady=(8, 0)
        )
        self.message = ttk.Label(frame, text="Siap")
        self.message.pack(anchor="w", pady=(0, 8))

        # --- Status Data Pixhawk ---
        pix_frame = ttk.LabelFrame(frame, text="Status Data Pixhawk", padding=8)
        pix_frame.pack(fill="x", pady=(0, 8))
        self.pixhawk_status = ttk.Label(
            pix_frame, text="-", font=("Consolas", 10), justify="left"
        )
        self.pixhawk_status.pack(anchor="w", fill="x")

        # --- Status Deteksi Foto ---
        det_frame = ttk.LabelFrame(frame, text="Status Deteksi Foto", padding=8)
        det_frame.pack(fill="x", pady=(0, 8))

        # Baris boxgreen
        row_green = ttk.Frame(det_frame)
        row_green.pack(fill="x", pady=(0, 4))
        ttk.Label(row_green, text="BOXGREEN :", width=12, anchor="w").pack(side="left")
        self.lbl_green = ttk.Label(row_green, text="STANDBY", width=24,
                                   font=("Consolas", 10, "bold"), foreground="#888888")
        self.lbl_green.pack(side="left")
        self.lbl_green_area = ttk.Label(row_green, text="area: 0 px²",
                                        font=("Consolas", 9), foreground="#888888")
        self.lbl_green_area.pack(side="left", padx=(6, 0))

        # Baris boxblue
        row_blue = ttk.Frame(det_frame)
        row_blue.pack(fill="x", pady=(0, 8))
        ttk.Label(row_blue, text="BOXBLUE  :", width=12, anchor="w").pack(side="left")
        self.lbl_blue = ttk.Label(row_blue, text="STANDBY", width=24,
                                  font=("Consolas", 10, "bold"), foreground="#888888")
        self.lbl_blue.pack(side="left")
        self.lbl_blue_area = ttk.Label(row_blue, text="area: 0 px²",
                                       font=("Consolas", 9), foreground="#888888")
        self.lbl_blue_area.pack(side="left", padx=(6, 0))

        # Tombol RESET FOTO
        ttk.Button(
            det_frame, text="RESET FOTO",
            command=lambda: self.ws.command("reset_photo"),
        ).pack(fill="x")

    def save_pid(self):
        try:
            values = {key: float(entry.get()) for key, entry in self.entries.items()}
        except ValueError:
            self.message.config(text="PID harus angka")
            return
        self.ws.command("set_pid", **values)
        self.message.config(text="PID dikirim")

    def update(self, state, status):
        self.status.config(text=status)
        if not state:
            return

        gps      = state.get("gps", {})
        battery  = state.get("battery1", {})
        sensors  = state.get("sensors", {})
        serial   = state.get("serial", {})
        servo    = state.get("servo", [0, 0, 0, 0])
        buoy     = state.get("buoy", {})
        mission  = state.get("mission", {})

        # Koneksi MAVLink
        connected  = state.get("connected", False)
        heartbeat  = sensors.get("heartbeat", False)
        mav_status = "[OK] TERHUBUNG" if (connected and heartbeat) else "[X] TERPUTUS"

        # GPS
        gps_fix  = "FIX" if gps.get("fix") else "NO FIX"
        gps_sats = gps.get("satellites", 0)
        gps_hdop = gps.get("hdop", 99.9)
        gps_lat  = gps.get("lat") or 0.0
        gps_lon  = gps.get("lon") or 0.0
        sog      = gps.get("sog", 0.0) or 0.0   # Speed Over Ground (m/s) dari GPS_RAW_INT
        cog      = gps.get("cog", 0.0) or 0.0   # Course Over Ground (derajat) dari GPS_RAW_INT

        # Heading dari sensor ATTITUDE Pixhawk (yaw radian → derajat 0–360)
        orientation = state.get("orientation", {})
        yaw_rad  = float(orientation.get("z") or 0.0)
        heading  = math.degrees(yaw_rad) % 360.0

        # Posisi XY arena dari LOCAL_POSITION_NED (East=X, North=Y)
        pos    = state.get("position", {})
        pos_x  = float(pos.get("x") or 0.0)
        pos_y  = float(pos.get("y") or 0.0)

        # Battery
        volt = battery.get("voltage", 0.0)
        curr = battery.get("current", 0.0)
        used = battery.get("used", 0.0)

        # Serial Teensy
        ser_ok   = serial.get("connected", False)
        ser_port = serial.get("port", "-")
        last_pwm = serial.get("last_pwm", 1500)

        # Servo
        s1, s2, s3, s4 = (servo + [0, 0, 0, 0])[:4]

        self.pixhawk_status.config(text=(
            f"MAVLink  : {mav_status}\n"
            f"Mode     : {state.get('mode', '-')}\n"
            f"Arm      : {state.get('arm', '-')}\n"
            f"Mission  : {state.get('missionState', '-')} "
            f"({mission.get('current', 0)}/{mission.get('total', 0)})\n"
            f"Arena    : {state.get('currentTrack', '-')}\n"
            "─────────────────────────────\n"
            f"GPS      : {gps_fix}  Sat={gps_sats}  HDOP={gps_hdop:.1f}\n"
            f"Lat/Lon  : {gps_lat:.6f} / {gps_lon:.6f}\n"
            f"SOG      : {sog:.2f} m/s\n"
            f"COG      : {cog:.1f}°\n"
            f"Heading  : {heading:.1f}° (yaw IMU)\n"
            "─────────────────────────────\n"
            f"Pos X    : {pos_x:.2f} m  (East arena)\n"
            f"Pos Y    : {pos_y:.2f} m  (North arena)\n"
            f"Speed    : {state.get('speed', 0.0):.2f} m/s\n"
            "─────────────────────────────\n"
            f"Batt     : {volt:.2f}V  {curr:.1f}A  Terpakai={used:.0f}mAh\n"
            "─────────────────────────────\n"
            f"Servo    : CH1={s1}  CH2={s2}  CH3={s3}  CH4={s4}\n"
            f"Buoy PWM : {buoy.get('servo_pwm', 1500)} µs  "
            f"Err={buoy.get('error_px', 0.0):.1f}px\n"
            "─────────────────────────────\n"
            f"Teensy   : {'[OK] CONNECTED' if ser_ok else '[X] DISCONNECTED'}  "
            f"Port={ser_port}  PWM={last_pwm}"
        ))

        # Hot-reload nilai PID dari server jika ada perubahan versi
        pid     = state.get("pid_config", {})
        version = pid.get("_version")
        if version != self.pid_version and self.root.focus_get() not in self.entries.values():
            for key, entry in self.entries.items():
                entry.delete(0, "end")
                entry.insert(0, str(pid.get(key, 0)))
            self.pid_version = version

        # ── Update status deteksi boxgreen / boxblue ──────────────────────────
        detection = state.get("detection", {})
        label          = detection.get("label", "STANDBY")
        foto_atas_ok   = detection.get("foto_atas_ready",  False)
        foto_bawah_ok  = detection.get("foto_bawah_ready", False)
        area_green     = int(detection.get("area_green", 0))
        area_blue      = int(detection.get("area_blue",  0))
        min_area       = 5000  # threshold yang dipakai di vision_worker

        # Boxgreen
        if foto_atas_ok:
            self.lbl_green.config(text="[OK] LOCKED & SAVED", foreground="#22cc55")
        elif area_green >= min_area:
            self.lbl_green.config(text="[*] TERDETEKSI",     foreground="#ffcc00")
        else:
            self.lbl_green.config(text="[-] STANDBY",        foreground="#888888")
        self.lbl_green_area.config(
            text=f"area: {area_green:,} px²  (min {min_area:,})",
            foreground="#22cc55" if foto_atas_ok else ("#ffcc00" if area_green >= min_area else "#888888"),
        )

        # Boxblue
        if foto_bawah_ok:
            self.lbl_blue.config(text="[OK] LOCKED & SAVED",  foreground="#33aaff")
        elif area_blue >= min_area:
            self.lbl_blue.config(text="[*] TERDETEKSI",      foreground="#ffcc00")
        else:
            self.lbl_blue.config(text="[-] STANDBY",         foreground="#888888")
        self.lbl_blue_area.config(
            text=f"area: {area_blue:,} px²  (min {min_area:,})",
            foreground="#33aaff" if foto_bawah_ok else ("#ffcc00" if area_blue >= min_area else "#888888"),
        )



def run(stop_event):
    root = tk.Tk()
    root.title("ASV Controls & PID")
    root.geometry("520x680+20+20")
    websocket = GUIWebSocket("controls")
    window = ControlsWindow(root, websocket)
    websocket.start()

    def refresh():
        if stop_event.is_set():
            websocket.stop()
            root.destroy()
            return
        state, _frame, status, _version, _frame_version = websocket.snapshot()
        window.update(state, status)
        root.after(50, refresh)

    def close():
        stop_event.set()
        websocket.stop()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", close)
    refresh()
    root.mainloop()
