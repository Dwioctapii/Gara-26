"""Komponen 4: window camera."""

import tkinter as tk

import cv2
import numpy as np

from .websocket import GUIWebSocket


class CameraWindow:
    def __init__(self, root):
        self.window = root
        self.window.title("ASV Camera")
        self.window.geometry("650x520+550+690")
        self.label = tk.Label(self.window, text="MENUNGGU KAMERA", bg="black", fg="white")
        self.label.pack(fill="both", expand=True)
        self.info = tk.Label(self.window, anchor="w", font=("Consolas", 10))
        self.info.pack(fill="x")
        self.photo = None

    def update(self, jpeg, state, status):
        frame = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
        if frame is None:
            return
        width = max(320, self.label.winfo_width())
        height = max(240, self.label.winfo_height())
        scale = min(width / frame.shape[1], height / frame.shape[0])
        frame = cv2.resize(frame, (int(frame.shape[1] * scale), int(frame.shape[0] * scale)))
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w = rgb.shape[:2]
        ppm = f"P6\n{w} {h}\n255\n".encode() + rgb.tobytes()
        self.photo = tk.PhotoImage(data=ppm, format="PPM")
        self.label.config(image=self.photo, text="")
        buoy = state.get("buoy", {})
        self.info.config(text=f"{status} | {buoy.get('mode', 'NONE')} | PWM {buoy.get('servo_pwm', 1500)}")


def run(stop_event):
    root = tk.Tk()
    window = CameraWindow(root)
    websocket = GUIWebSocket("camera", camera=True)
    websocket.start()
    last_frame_version = -1

    def refresh():
        nonlocal last_frame_version
        if stop_event.is_set():
            websocket.stop()
            root.destroy()
            return
        state, frame, status, _version, frame_version = websocket.snapshot()
        if frame_version != last_frame_version and frame:
            window.update(frame, state, status)
            last_frame_version = frame_version
        root.after(15, refresh)

    def close():
        stop_event.set()
        websocket.stop()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", close)
    refresh()
    root.mainloop()
