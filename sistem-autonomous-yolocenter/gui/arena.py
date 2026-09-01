"""Komponen 3: window arena Tkinter Canvas."""

import math
import tkinter as tk

from .websocket import GUIWebSocket


RED = [(-4, 13), (-5, 16), (-4, 19), (-10, 28), (-13, 28), (-16, 28), (-19, 28), (-27, 19), (-28, 16), (-28, 13)]
GREEN = [(-2, 13), (-3, 16), (-2, 19), (-10, 26), (-13, 26), (-16, 26), (-19, 26), (-25, 19), (-26, 16), (-26, 13)]
BLUE = [(-4, 1.7), (-4, 2.4), (-4, 3.1)]


class ArenaWindow:
    def __init__(self, root):
        self.window = root
        self.window.title("ASV Arena")
        self.window.geometry("650x650+550+20")
        self.canvas = tk.Canvas(self.window, bg="#111820", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.track = "A"
        self.trace = []
        self.state = {}
        self.canvas.bind("<Configure>", lambda _event: self.draw())

    def xy(self, x, y):
        margin = 40
        width = max(1, self.canvas.winfo_width() - margin * 2)
        height = max(1, self.canvas.winfo_height() - margin * 2)
        x_min = -30 if self.track == "A" else 0
        return margin + (x - x_min) / 30 * width, margin + (30 - y) / 30 * height

    def draw(self):
        self.canvas.delete("all")
        for value in range(0, 31, 5):
            x_value = (-30 if self.track == "A" else 0) + value
            x, _ = self.xy(x_value, 0)
            _, y0 = self.xy(0, 0)
            _, y1 = self.xy(0, 30)
            self.canvas.create_line(x, y0, x, y1, fill="#263746", dash=(3, 4))
            _, y = self.xy(0, value)
            x0, _ = self.xy(-30 if self.track == "A" else 0, 0)
            x1, _ = self.xy(0 if self.track == "A" else 30, 0)
            self.canvas.create_line(x0, y, x1, y, fill="#263746", dash=(3, 4))

        sign = -1 if self.track == "B" else 1
        for points, color in ((RED, "#ff445c"), (GREEN, "#35e67a"), (BLUE, "#2bbcff")):
            for px, py in points:
                x, y = self.xy(px * sign, py)
                self.canvas.create_oval(x - 5, y - 5, x + 5, y + 5, fill=color, outline="")

        if len(self.trace) > 1:
            coords = [value for point in self.trace for value in self.xy(*point)]
            self.canvas.create_line(*coords, fill="#2ab7ff", width=2)

        position = self.position(self.state)
        if position:
            x, y = self.xy(*position)
            self.canvas.create_oval(x - 7, y - 7, x + 7, y + 7, fill="#33d7ff", outline="white")
            yaw = float(self.state.get("orientation", {}).get("z") or 0)
            if self.track == "B":
                yaw = -yaw
            self.canvas.create_line(x, y, x + 28 * math.sin(yaw), y - 28 * math.cos(yaw), fill="white", width=2, arrow="last")

        self.canvas.create_text(self.canvas.winfo_width() / 2, 18, text=f"ARENA {self.track}", fill="#45d9f5", font=("Segoe UI", 14, "bold"))

    def position(self, state):
        position = state.get("position", {})
        x = float(position.get("x") or 0) - 3
        y = float(position.get("y") or 0) + 2
        return (-x if self.track == "B" else x, y)

    def update(self, state):
        if not state:
            return
        new_track = state.get("currentTrack", "A")
        if new_track not in {"A", "B"}:
            new_track = "A"
        if new_track != self.track:
            self.track = new_track
            self.trace.clear()
        self.state = state
        position = self.position(state)
        if not self.trace or math.dist(position, self.trace[-1]) > 0.05:
            self.trace.append(position)
            self.trace = self.trace[-1000:]
        self.draw()


def run(stop_event):
    root = tk.Tk()
    window = ArenaWindow(root)
    websocket = GUIWebSocket("arena")
    websocket.start()
    last_version = -1

    def refresh():
        nonlocal last_version
        if stop_event.is_set():
            websocket.stop()
            root.destroy()
            return
        state, _frame, status, version, _frame_version = websocket.snapshot()
        if version != last_version and state:
            window.update(state)
            root.title(f"ASV Arena - {status}")
            last_version = version
        root.after(50, refresh)

    def close():
        stop_event.set()
        websocket.stop()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", close)
    refresh()
    root.mainloop()
