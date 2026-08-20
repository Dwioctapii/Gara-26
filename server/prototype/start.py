import matplotlib.pyplot as plt
import matplotlib.animation as animation
import math
import os
from pymavlink import mavutil
import matplotlib.transforms as transforms
import numpy as np

# ---> TAMBAHAN UNTUK WEBSOCKET <---
import json
import asyncio
import websockets
import threading

# ==========================================
# SERIAL MAVLINK (Pixhawk di Ubuntu)
# ==========================================
PORT = "/dev/ttyACM0"  # Sesuaikan port Pixhawk kamu
BAUD = 115200          # Sesuaikan baud rate

try:
    print(f"Menghubungkan ke Pixhawk di {PORT}...")
    master = mavutil.mavlink_connection(PORT, baud=BAUD)
    
    # Tunggu heartbeat pertama dari Pixhawk
    master.wait_heartbeat(timeout=5)
    print(f"Berhasil terhubung ke Pixhawk! System ID: {master.target_system}")

    master.mav.request_data_stream_send(
        master.target_system,
        master.target_component,
        mavutil.mavlink.MAV_DATA_STREAM_ALL,
        10,  # Frekuensi Hz (10 Hz)
        1    # Start stream
    )

except Exception as e:
    print(f"Error membuka port/MAVLink {PORT}: {e}")
    print("Tips: Jalankan 'sudo chmod a+rw /dev/ttyACM0 /dev/ttyACM1' jika permission denied.")
    exit(1)

# ==========================================
# ARENA
# ==========================================
grid_size = 30
red_square = (-3, 2)
green_square = (-18, 3)
blue_square = (-21, 6)

red_balls = [
    (-3.5, 9), (-4.8, 12), (-3, 14.6),
    (-9, 20.5), (-11, 20.5), (-13, 20.5),
    (-15, 20.5), (-22, 17),
    (-23.5, 13.5), (-23.5, 9.5)
]

green_balls = [
    (-2, 9), (-3.3, 12), (-1.4, 14.6),
    (-9, 22), (-11, 22), (-13, 22),
    (-15, 22), (-20.5, 17),
    (-22.2, 13.5), (-22.2, 9.5)
]

# ==========================================
# LOAD WAYPOINT
# ==========================================
waypoints = []
waypoint_file = "waypoint_xy.txt"

if os.path.exists(waypoint_file):
    with open(waypoint_file, "r") as f:
        for line in f:
            line_str = line.strip()
            if line_str:
                x, y = map(float, line_str.split(","))
                waypoints.append((x, y))
else:
    print(f"Peringatan: File {waypoint_file} tidak ditemukan di direktori saat ini.")

# ==========================================
# FIGURE & MAP AXIS
# ==========================================
fig, ax = plt.subplots(figsize=(8, 8))
ax.set_xlim(-30, 0)
ax.set_ylim(0, 30)
ax.set_aspect("equal")
ax.set_xticks(range(-30, 1, 5))
ax.set_yticks(range(0, 31, 5))
ax.grid(True)

for x, y in red_balls:
    ax.add_patch(plt.Circle((x, y), 0.3, color='red'))
for x, y in green_balls:
    ax.add_patch(plt.Circle((x, y), 0.3, color='green'))

ax.add_patch(plt.Rectangle((red_square[0] - 0.5, red_square[1] - 0.5), 1, 1, color='red'))
ax.add_patch(plt.Rectangle((green_square[0] - 0.5, green_square[1] - 0.5), 1, 1, color='green'))
ax.add_patch(plt.Rectangle((blue_square[0] - 0.5, blue_square[1] - 0.5), 1, 1, color='blue'))

if waypoints:
    xs = [p[0] for p in waypoints]
    ys = [p[1] for p in waypoints]
    ax.plot(xs, ys, 'k--', label="Waypoint")

# ==========================================
# ROBOT & TRAJECTORY
# ==========================================
robot, = ax.plot([], [], 'bo', markersize=8)
trace_x = []
trace_y = []
trace, = ax.plot([], [], 'b', linewidth=2)
arrow = None

# Variabel Global
current_x = None
current_y = None
current_yaw_rad = 0.0  
raw_yaw_rad = 0.0      
current_lat = 0.0
current_lon = 0.0
yaw_offset = None  
lat0 = None
lon0 = None
current_sog = 0.0      
current_cog = 0.0      

# ==========================================
# COMPASS INSET AXIS (Pojok Kanan Atas)
# ==========================================
ax_compass = fig.add_axes([0.72, 0.72, 0.18, 0.18], polar=False) 
ax_compass.set_xlim(-1.2, 1.2)
ax_compass.set_ylim(-1.2, 1.2)
ax_compass.set_aspect('equal')
ax_compass.axis('off') 

circle_compass = plt.Circle((0, 0), 1.0, color='black', fill=False, linewidth=1)
ax_compass.add_patch(circle_compass)

label_fontsize = 11
text_u = ax_compass.text(0, 1.05, 'U', color='black', fontsize=label_fontsize, ha='center', va='bottom', weight='bold')
text_s = ax_compass.text(0, -1.05, 'S', color='black', fontsize=label_fontsize, ha='center', va='top', weight='bold')
text_t = ax_compass.text(1.05, 0, 'T', color='black', fontsize=label_fontsize, ha='left', va='center', weight='bold')
text_b = ax_compass.text(-1.05, 0, 'B', color='black', fontsize=label_fontsize, ha='right', va='center', weight='bold')

arrow_poly_coords = np.array([[0, 0.9], [0.15, 0], [-0.15, 0]])
compass_arrow_patch = plt.Polygon(arrow_poly_coords, closed=True, facecolor='red', edgecolor='black')
ax_compass.add_patch(compass_arrow_patch)

text_info = fig.text(
    0.72, 0.69, 
    "Menunggu Data Pixhawk...", 
    fontsize=9, 
    family='monospace', 
    verticalalignment='top',
    bbox=dict(boxstyle='round,pad=0.3', facecolor='white', alpha=0.8, edgecolor='gray')
)

# ==========================================
# GPS ORIGIN & CONVERSION
# ==========================================
def gps_to_xy(lat, lon, heading_offset):
    global lat0, lon0
    if lat0 is None:
        lat0 = lat
        lon0 = lon
        print(f"Origin GPS tersimpan di: Lat {lat0:.8f}, Lon {lon0:.8f}")

    dx_east = (lon - lon0) * 111320 * math.cos(math.radians(lat0))
    dy_north = (lat - lat0) * 111320

    x_rotated = dx_east * math.cos(heading_offset) - dy_north * math.sin(heading_offset)
    y_rotated = dx_east * math.sin(heading_offset) + dy_north * math.cos(heading_offset)

    x = red_square[0] + x_rotated
    y = red_square[1] + y_rotated
    return x, y

# ==========================================
# BACKGROUND THREAD WEBSOCKET SERVER 
# ==========================================
async def kirim_data_telemetri(websocket, path=""):
    print(f"\n[WEBSOCKET] Web Client Terhubung: {websocket.remote_address}")
    try:
        while True:
            if current_lat != 0.0 and current_lon != 0.0:
                heading_earth_deg = (math.degrees(raw_yaw_rad) + 360) % 360
                
                data_paket = {
                    "lat": current_lat,
                    "lon": current_lon,
                    "x": round(current_x, 2) if current_x is not None else 0.0,
                    "y": round(current_y, 2) if current_y is not None else 0.0,
                    "kompas": round(heading_earth_deg, 2),
                    "sog": round(current_sog, 2),
                    "cog": round(current_cog, 2)
                }
                
                pesan_json = json.dumps(data_paket)
                await websocket.send(pesan_json)
            
            await asyncio.sleep(0.1) 
            
    except websockets.exceptions.ConnectionClosed:
        print("\n[WEBSOCKET] Web Client Terputus.")
    except Exception as e:
        print(f"\n[WEBSOCKET ERROR] Masalah saat kirim data: {e}")

def jalankan_server_websocket():
    try:
        print("\n[WEBSOCKET] Sedang menyiapkan server...")
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        server = websockets.serve(kirim_data_telemetri, "192.168.0.4", 8765)
        loop.run_until_complete(server)
        print("[WEBSOCKET] Server AKTIF dan SIAP di Port 8765!")
        loop.run_forever()
    except Exception as e:
        print(f"\n[CRITICAL ERROR] Server WebSocket gagal hidup: {e}")

print("[INFO] Memulai Thread WebSocket di latar belakang...")
ws_thread = threading.Thread(target=jalankan_server_websocket, daemon=True)
ws_thread.start()

# ==========================================
# UPDATE ANIMATION
# ==========================================
def update(frame):
    global arrow, current_x, current_y, current_yaw_rad, raw_yaw_rad, current_lat, current_lon, yaw_offset, current_sog, current_cog

    try:
        while True:
            msg = master.recv_match(type=['GLOBAL_POSITION_INT', 'GPS_RAW_INT', 'ATTITUDE'], blocking=False)
            if not msg:
                break

            msg_type = msg.get_type()

            if msg_type == 'ATTITUDE':
                raw_yaw_rad = msg.yaw
                if yaw_offset is None:
                    yaw_offset = raw_yaw_rad
                    print(f"Kalibrasi Arena Berhasil! Offset Awal: {math.degrees(yaw_offset):.2f}°")

                relative_yaw = raw_yaw_rad - yaw_offset
                current_yaw_rad = math.atan2(math.sin(relative_yaw), math.cos(relative_yaw))

            elif msg_type in ['GLOBAL_POSITION_INT', 'GPS_RAW_INT']:
                lat = msg.lat / 1e7
                lon = msg.lon / 1e7
                
                # --- PERBAIKAN SOG KE KNOTS BESERTA FILTER ERROR 65535 ---
                if msg_type == 'GPS_RAW_INT':
                    if msg.vel != 65535:
                        # (cm/s / 100) * 1.94384 = Knots
                        current_sog = (msg.vel / 100.0) * 1.94384  
                    if msg.cog != 65535:           
                        current_cog = msg.cog / 100.0  

                if lat != 0 and lon != 0 and yaw_offset is not None:
                    current_lat = lat
                    current_lon = lon
                    
                    current_x, current_y = gps_to_xy(lat, lon, yaw_offset)

                    if not trace_x or (current_x != trace_x[-1] or current_y != trace_y[-1]):
                        trace_x.append(current_x)
                        trace_y.append(current_y)

        rot_angle_earth = raw_yaw_rad 

        new_circle_transform = transforms.Affine2D().rotate(rot_angle_earth) + ax_compass.transData
        circle_compass.set_transform(new_circle_transform)

        cos_a = math.cos(rot_angle_earth)
        sin_a = math.sin(rot_angle_earth)

        text_u.set_position((-1.05 * sin_a, 1.05 * cos_a))
        text_s.set_position((1.05 * sin_a, -1.05 * cos_a))
        text_t.set_position((1.05 * cos_a, 1.05 * sin_a))
        text_b.set_position((-1.05 * cos_a, -1.05 * sin_a))

        if current_x is not None and current_y is not None:
            robot.set_data([current_x], [current_y])
            trace.set_data(trace_x, trace_y)

            heading_earth_deg = (math.degrees(raw_yaw_rad) + 360) % 360

            # Ganti teks di terminal matplotlib menjadi Knots
            text_info.set_text(
                f"Lat : {current_lat:.7f}\n"
                f"Lon : {current_lon:.7f}\n"
                f"X   : {current_x:.2f} m\n"
                f"Y   : {current_y:.2f} m\n"
                f"SOG : {current_sog:.2f} Knots\n"
                f"Head: {heading_earth_deg:.1f}°"
            )

            if arrow is not None:
                arrow.remove()

            arrow_length = 1.2
            vx = arrow_length * math.sin(current_yaw_rad)
            vy = arrow_length * math.cos(current_yaw_rad)

            arrow = ax.arrow(
                current_x, current_y,
                vx, vy,
                head_width=0.4,
                head_length=0.5,
                fc="blue",
                ec="blue"
            )

    except Exception as e:
        print(f"Error MAVLink: {e}")

    return robot, trace, circle_compass, text_u, text_s, text_t, text_b

# ==========================================
# ANIMATION
# ==========================================
ani = animation.FuncAnimation(
    fig,
    update,
    interval=20,
    blit=False,
    cache_frame_data=False
)

plt.title("Realtime Pixhawk Tracking & Multi-Reference Heading")
plt.show()