"""Komponen 1: debugging di terminal."""

import time

from .websocket import GUIWebSocket


class TerminalDebug:
    def __init__(self):
        self.previous = None

    def update(self, state, status):
        buoy = state.get("buoy", {})
        current = (
            status, state.get("mode"), state.get("arm"),
            state.get("missionState"), state.get("currentTrack"),
            buoy.get("mode"), buoy.get("servo_pwm"),
        )
        if current != self.previous:
            print(
                f"[GUI] {status} | mode={current[1]} arm={current[2]} "
                f"mission={current[3]} arena={current[4]} "
                f"buoy={current[5]} pwm={current[6]}"
            )
            self.previous = current


def run(stop_event):
    websocket = GUIWebSocket("debug")
    debug = TerminalDebug()
    websocket.start()
    try:
        while not stop_event.is_set():
            state, _frame, status, _version, _frame_version = websocket.snapshot()
            if state:
                debug.update(state, status)
            time.sleep(0.1)
    finally:
        websocket.stop()
