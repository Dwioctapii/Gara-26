"""Debug output bersama untuk worker jaringan."""

import json
import os
import time


DEBUG_ACTIVE = os.getenv("ASV_DEBUG", "1") == "1"


def _debug(channel: str, event: str, detail=None) -> None:
    if not DEBUG_ACTIVE:
        return
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    value = "" if detail is None else json.dumps(detail, ensure_ascii=False, default=str)
    print(f"[{stamp}][DEBUG][{channel}] {event} {value}")

