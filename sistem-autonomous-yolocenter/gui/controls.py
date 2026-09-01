"""Komponen 2: tombol dan form PID Tkinter."""

import tkinter as tk
from tkinter import ttk

from .websocket import GUIWebSocket


class ControlsWindow:
    def __init__(self, root, websocket):
        self.root = root
        self.ws = websocket
        self.pid_version = None
        self.entries = {}

        frame = ttk.Frame(root, padding=12)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="ASV CONTROL", font=("Segoe UI", 18, "bold")).pack(anchor="w")
        self.status = ttk.Label(frame, text="CONNECTING")
        self.status.pack(anchor="w", pady=(0, 10))
        self.telemetry = ttk.Label(frame, text="-", font=("Consolas", 10))
        self.telemetry.pack(fill="x", pady=(0, 10))

        buttons = ttk.LabelFrame(frame, text="Kendali", padding=8)
        buttons.pack(fill="x")
        commands = [
            ("ARM", "arm", {"action": "arm"}),
            ("DISARM", "arm", {"action": "disarm"}),
            ("E-STOP", "arm", {"action": "estop"}),
            ("MANUAL", "set_mode", {"mode": "Manual"}),
            ("AUTO", "set_mode", {"mode": "Auto"}),
            ("RTL", "go_home", {}),
            ("START", "mission", {"action": "start"}),
            ("PAUSE", "mission", {"action": "pause"}),
            ("STOP", "mission", {"action": "stop"}),
            ("HOLD", "hold_position", {}),
            ("SET HOME", "set_home", {}),
            ("RESET", "reset_mission", {}),
        ]
        for index, (text, command, data) in enumerate(commands):
            ttk.Button(
                buttons, text=text,
                command=lambda c=command, d=data: self.ws.command(c, **d),
            ).grid(row=index // 3, column=index % 3, sticky="ew", padx=2, pady=2)
        for column in range(3):
            buttons.columnconfigure(column, weight=1)

        tracks = ttk.Frame(frame)
        tracks.pack(fill="x", pady=10)
        ttk.Button(tracks, text="ARENA A", command=lambda: self.ws.command("set_track", track="A")).pack(side="left", expand=True, fill="x")
        ttk.Button(tracks, text="ARENA B", command=lambda: self.ws.command("set_track", track="B")).pack(side="left", expand=True, fill="x", padx=(5, 0))

        pid = ttk.LabelFrame(frame, text="PID", padding=8)
        pid.pack(fill="x")
        for row, key in enumerate(("kp", "ki", "kd", "deadband", "integral_limit")):
            ttk.Label(pid, text=key).grid(row=row, column=0, sticky="w")
            entry = ttk.Entry(pid)
            entry.grid(row=row, column=1, sticky="ew", padx=(8, 0), pady=2)
            self.entries[key] = entry
        pid.columnconfigure(1, weight=1)
        ttk.Button(pid, text="SIMPAN PID", command=self.save_pid).grid(row=5, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        self.message = ttk.Label(frame, text="Siap")
        self.message.pack(anchor="w", pady=8)

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
        gps = state.get("gps", {})
        buoy = state.get("buoy", {})
        self.telemetry.config(text=(
            f"MODE    : {state.get('mode')}\n"
            f"ARM     : {state.get('arm')}\n"
            f"MISSION : {state.get('missionState')}\n"
            f"ARENA   : {state.get('currentTrack')}\n"
            f"GPS     : {'FIX' if gps.get('fix') else 'NO FIX'} ({gps.get('satellites', 0)} sat)\n"
            f"BUOY    : {buoy.get('mode', 'NONE')} / PWM {buoy.get('servo_pwm', 1500)}"
        ))
        pid = state.get("pid_config", {})
        version = pid.get("_version")
        if version != self.pid_version and self.root.focus_get() not in self.entries.values():
            for key, entry in self.entries.items():
                entry.delete(0, "end")
                entry.insert(0, str(pid.get(key, 0)))
            self.pid_version = version


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
