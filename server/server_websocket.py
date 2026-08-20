"""WebSocket telemetry broadcaster and command receiver."""
import asyncio, json, os
import websockets
from state import store

async def serve(command_handler=None):
    host=os.getenv("ASV_WS_HOST","0.0.0.0"); port=int(os.getenv("ASV_WS_PORT","8765")); hz=max(1.,float(os.getenv("ASV_BROADCAST_HZ","10")))
    async def client(ws):
        print("[WS] connected",ws.remote_address)
        async def tx():
            while True: await ws.send(json.dumps(store.snapshot(),separators=(",",":"))); await asyncio.sleep(1/hz)
        async def rx():
            async for raw in ws:
                try:
                    cmd=json.loads(raw)
                    if not isinstance(cmd,dict) or not isinstance(cmd.get("command"),str): raise ValueError("invalid command")
                    store.command(cmd); result=await command_handler(cmd) if command_handler else None
                    await ws.send(json.dumps({"type":"ack","id":cmd.get("id"),"ok":True,"result":result}))
                except (ValueError,json.JSONDecodeError) as exc: await ws.send(json.dumps({"type":"ack","ok":False,"error":str(exc)}))
        tasks={asyncio.create_task(tx()),asyncio.create_task(rx())}; done,pending=await asyncio.wait(tasks,return_when=asyncio.FIRST_COMPLETED)
        for task in pending: task.cancel()
        await asyncio.gather(*done,return_exceptions=True)
    print(f"[WS] ws://{host}:{port}")
    async with websockets.serve(client,host,port,ping_interval=20,ping_timeout=20,max_size=1_000_000): await asyncio.Future()
if __name__=="__main__": asyncio.run(serve())
