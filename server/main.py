"""Run HTTP, WebSocket, and MAVLink workers."""
import asyncio, threading
from mavlink_bridge import MavlinkBridge
from server_http_asv import serve as http
from server_websocket import serve as websocket

async def main():
    bridge=MavlinkBridge(); bridge.start(); threading.Thread(target=http,name="http",daemon=True).start()
    try: await websocket(bridge.handle_command)
    finally: bridge.stop()
if __name__=="__main__":
    try: asyncio.run(main())
    except KeyboardInterrupt: print("\n[ASV] stopped")
