"""MAVLink telemetry reader with opt-in vehicle commands."""
import asyncio, math, os, threading, time
from state import store
try: from pymavlink import mavutil
except ImportError: mavutil=None

class MavlinkBridge:
    def __init__(self):
        self.endpoint=os.getenv("ASV_MAVLINK","udpin:0.0.0.0:14550")
        self.baud=int(os.getenv("ASV_MAVLINK_BAUD","115200")); self.enabled=os.getenv("ASV_ENABLE_COMMANDS","0")=="1"
        self.master=None; self.stop_event=threading.Event()
    def start(self): threading.Thread(target=self._run,name="mavlink",daemon=True).start()
    def stop(self): self.stop_event.set(); self.master and self.master.close()
    def _run(self):
        if mavutil is None: return store.update({"lastError":"pymavlink belum terpasang"})
        while not self.stop_event.is_set():
            try:
                print("[MAVLink]",self.endpoint); self.master=mavutil.mavlink_connection(self.endpoint,baud=self.baud)
                if self.master.wait_heartbeat(timeout=10) is None: raise TimeoutError("heartbeat timeout")
                store.update({"connected":True,"sensors":{"heartbeat":True},"lastError":None})
                while not self.stop_event.is_set():
                    msg=self.master.recv_match(blocking=True,timeout=.5)
                    if msg: self._consume(msg)
            except Exception as exc:
                store.update({"connected":False,"sensors":{"heartbeat":False},"lastError":f"MAVLink: {exc}"}); time.sleep(2)
    def _consume(self,m):
        kind=m.get_type(); patch={"connected":True,"sensors":{"heartbeat":True}}
        if kind=="BAD_DATA": return
        if kind=="HEARTBEAT":
            armed=bool(m.base_mode&mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED); patch.update(mode=self.master.flightmode or "Manual",arm="Armed" if armed else "Disarmed")
        elif kind=="ATTITUDE": patch.update(orientation={"x":float(m.roll),"y":float(m.pitch),"z":float(m.yaw),"w":1.},angular={"x":float(m.rollspeed),"y":float(m.pitchspeed),"z":float(m.yawspeed)})
        elif kind=="GLOBAL_POSITION_INT":
            vx,vy=m.vx/100.,m.vy/100.; heading=0. if m.hdg==65535 else m.hdg/100.
            patch.update(gps={"lat":m.lat/1e7,"lon":m.lon/1e7,"sog":math.hypot(vx,vy),"cog":heading,"fix":m.lat!=0 and m.lon!=0},linear={"x":vx,"y":vy,"z":m.vz/100.},speed=math.hypot(vx,vy),position={"z":m.relative_alt/1000.})
        elif kind=="LOCAL_POSITION_NED": patch["position"]={"x":float(m.y),"y":float(m.x),"z":float(-m.z)}
        elif kind=="GPS_RAW_INT": patch["gps"]={"satellites":int(m.satellites_visible),"hdop":m.eph/100. if m.eph!=65535 else 99.9,"fix":m.fix_type>=3}
        elif kind=="SYS_STATUS": patch["battery1"]={"voltage":max(0,m.voltage_battery)/1000.,"current":max(0,m.current_battery)/100.}
        elif kind=="BATTERY_STATUS":
            cells=[v for v in m.voltages if v not in (0,65535)]; patch["battery1"]={"voltage":sum(cells)/1000.,"current":max(0,m.current_battery)/100.,"used":max(0,m.current_consumed),"temp":0 if m.temperature==32767 else m.temperature/100.}
        elif kind=="MISSION_CURRENT": patch["mission"]={"current":int(m.seq),"total":int(getattr(m,"total",0))}
        elif kind=="SERVO_OUTPUT_RAW": patch["servo"]=[m.servo1_raw,m.servo2_raw,m.servo3_raw,m.servo4_raw]
        store.update(patch)
    async def handle_command(self,cmd):
        if not self.enabled: return {"sent":False,"reason":"ASV_ENABLE_COMMANDS=0"}
        if self.master is None: raise RuntimeError("MAVLink belum terhubung")
        return await asyncio.to_thread(self._send,cmd)
    def _send(self,cmd):
        name,action=cmd["command"],cmd.get("action"); mapping=self.master.mode_mapping() or {}
        if name=="arm":
            if action=="estop": self.master.mav.command_long_send(self.master.target_system,self.master.target_component,mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM,0,0,21196,0,0,0,0,0)
            elif action=="arm": self.master.arducopter_arm()
            else: self.master.arducopter_disarm()
        elif name in ("set_mode","go_home","hold_position"):
            mode={"Manual":"MANUAL","Auto":"AUTO","Return Home":"RTL"}.get(cmd.get("mode")) if name=="set_mode" else ("RTL" if name=="go_home" else ("LOITER" if "LOITER" in mapping else "HOLD"))
            if mode not in mapping: raise ValueError(f"mode {mode} tidak tersedia")
            self.master.set_mode(mapping[mode])
        elif name=="mission" and action=="start": self.master.mav.command_long_send(self.master.target_system,self.master.target_component,mavutil.mavlink.MAV_CMD_MISSION_START,0,0,0,0,0,0,0,0)
        elif name=="set_home": self.master.mav.command_long_send(self.master.target_system,self.master.target_component,mavutil.mavlink.MAV_CMD_DO_SET_HOME,0,1,0,0,0,0,0,0)
        else: return {"sent":False,"reason":"state-only command"}
        return {"sent":True}
