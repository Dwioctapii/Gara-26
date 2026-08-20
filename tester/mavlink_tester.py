import math
import time

from pymavlink import mavutil


PORT = (
    "/dev/serial/by-id/"
    "usb-Holybro_Pixhawk6C_410021001951343034343031-if00"
)

DISPLAY_INTERVAL = 1.0

MESSAGE_TYPES = [
    "HEARTBEAT",
    "ATTITUDE",
    "GLOBAL_POSITION_INT",
    "GPS_RAW_INT",
    "GPS2_RAW",
    "SYS_STATUS",
    "POWER_STATUS",
    "BATTERY_STATUS",
    "MISSION_CURRENT",
    "SERVO_OUTPUT_RAW",
    "EKF_STATUS_REPORT",
    "VIBRATION",
    "STATUSTEXT",
]

GPS_FIX = {
    0: "NO GPS",
    1: "NO FIX",
    2: "2D",
    3: "3D",
    4: "DGPS",
    5: "RTK FLOAT",
    6: "RTK FIXED",
    7: "STATIC",
    8: "PPP",
}

SEVERITY = {
    0: "EMERGENCY",
    1: "ALERT",
    2: "CRITICAL",
    3: "ERROR",
    4: "WARNING",
    5: "NOTICE",
    6: "INFO",
    7: "DEBUG",
}


def field(message, name, default=None):
    if message is None:
        return default
    return getattr(message, name, default)


def degrees(radians):
    if radians is None:
        return None
    return math.degrees(radians)


def gps_summary(name, gps):
    if gps is None:
        return f"{name}: belum ada data"

    fix_type = field(gps, "fix_type", 0)
    satellites = field(gps, "satellites_visible", 0)

    h_acc = field(gps, "h_acc", 0)

    if 0 < h_acc < 4294967295:
        accuracy = h_acc / 1000.0  # mm -> m
    else:
        eph = field(gps, "eph", 65535)
        accuracy = eph / 100.0 if eph != 65535 else None

    accuracy_text = (
        f"{accuracy:.2f} m"
        if accuracy is not None
        else "tidak diketahui"
    )

    return (
        f"{name}: {GPS_FIX.get(fix_type, str(fix_type))} | "
        f"sat={satellites} | akurasi={accuracy_text}"
    )


def battery_summary(battery):
    if battery is None:
        return "Baterai: belum ada data"

    raw_voltages = field(battery, "voltages", [])
    valid_cells = [
        voltage
        for voltage in raw_voltages
        if voltage not in (0, 65535)
    ]

    total_mv = sum(valid_cells)
    voltage = total_mv / 1000.0 if total_mv >= 1000 else None

    current_raw = field(battery, "current_battery", -1)
    current = current_raw / 100.0 if current_raw >= 0 else None
    remaining = field(battery, "battery_remaining", -1)

    voltage_text = (
        f"{voltage:.2f} V"
        if voltage is not None
        else "INVALID"
    )
    current_text = (
        f"{current:.2f} A"
        if current is not None
        else "N/A"
    )
    remaining_text = (
        f"{remaining}%"
        if remaining >= 0
        else "N/A"
    )

    return (
        f"Baterai: {voltage_text} | "
        f"arus={current_text} | sisa={remaining_text}"
    )


def display(latest, connection, last_status):
    heartbeat = latest.get("HEARTBEAT")
    attitude = latest.get("ATTITUDE")
    position = latest.get("GLOBAL_POSITION_INT")
    power = latest.get("POWER_STATUS")
    mission = latest.get("MISSION_CURRENT")
    servo = latest.get("SERVO_OUTPUT_RAW")
    vibration = latest.get("VIBRATION")
    ekf = latest.get("EKF_STATUS_REPORT")

    base_mode = field(heartbeat, "base_mode", 0)
    armed = bool(
        base_mode
        & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED
    )

    vehicle_state = "ARMED" if armed else "DISARMED"
    mode = connection.flightmode or "UNKNOWN"

    latitude = field(position, "lat", 0) / 1e7
    longitude = field(position, "lon", 0) / 1e7
    altitude = field(position, "alt", 0) / 1000.0
    relative_altitude = field(position, "relative_alt", 0) / 1000.0

    heading_raw = field(position, "hdg", 65535)
    heading = (
        heading_raw / 100.0
        if heading_raw != 65535
        else None
    )

    vx = field(position, "vx", 0) / 100.0
    vy = field(position, "vy", 0) / 100.0
    speed = math.hypot(vx, vy)

    roll = degrees(field(attitude, "roll", 0))
    pitch = degrees(field(attitude, "pitch", 0))
    yaw = degrees(field(attitude, "yaw", 0)) % 360

    vcc = field(power, "Vcc", 0) / 1000.0

    print("\033[2J\033[H", end="")
    print("=" * 65)
    print("MAVLINK ASV DASHBOARD")
    print("=" * 65)

    print(
        f"System     : {connection.target_system} | "
        f"mode={mode} | {vehicle_state}"
    )

    print(
        f"Posisi     : {latitude:.7f}, {longitude:.7f}"
    )

    heading_text = (
        f"{heading:.1f}°"
        if heading is not None
        else "N/A"
    )

    print(
        f"Navigasi   : heading={heading_text} | "
        f"speed={speed:.2f} m/s"
    )

    print(
        f"Altitude   : MSL={altitude:.2f} m | "
        f"relative={relative_altitude:.2f} m"
    )

    print(
        f"Attitude   : roll={roll:.1f}° | "
        f"pitch={pitch:.1f}° | yaw={yaw:.1f}°"
    )

    print(gps_summary("GPS 1", latest.get("GPS_RAW_INT")))
    print(gps_summary("GPS 2", latest.get("GPS2_RAW")))
    print(battery_summary(latest.get("BATTERY_STATUS")))
    print(f"Power FC   : {vcc:.2f} V")

    if mission is not None:
        current = field(mission, "seq", 0)
        total = field(mission, "total", 0)

        print(
            f"Mission    : waypoint={current + 1}/{total}"
            if total > 0
            else "Mission    : tidak ada"
        )

    if servo is not None:
        print(
            "Servo PWM  : "
            f"S1={field(servo, 'servo1_raw', 0)} | "
            f"S2={field(servo, 'servo2_raw', 0)} | "
            f"S3={field(servo, 'servo3_raw', 0)} | "
            f"S4={field(servo, 'servo4_raw', 0)}"
        )

    if vibration is not None:
        print(
            "Vibration  : "
            f"X={field(vibration, 'vibration_x', 0):.3f} | "
            f"Y={field(vibration, 'vibration_y', 0):.3f} | "
            f"Z={field(vibration, 'vibration_z', 0):.3f} | "
            f"clip={field(vibration, 'clipping_0', 0)}/"
            f"{field(vibration, 'clipping_1', 0)}/"
            f"{field(vibration, 'clipping_2', 0)}"
        )

    if ekf is not None:
        print(
            "EKF         : "
            f"flags={field(ekf, 'flags', 0)} | "
            f"posH={field(ekf, 'pos_horiz_variance', 0):.3f} | "
            f"posV={field(ekf, 'pos_vert_variance', 0):.3f}"
        )

    if last_status:
        print(
            f"Pesan FC    : [{last_status['severity']}] "
            f"{last_status['text']}"
        )

    print("=" * 65)
    print("Ctrl+C untuk berhenti")


connection = mavutil.mavlink_connection(PORT, baud=115200)

print(f"Membuka {PORT}")
print("Menunggu heartbeat...")

heartbeat = connection.wait_heartbeat(timeout=15)

if heartbeat is None:
    raise RuntimeError("Heartbeat tidak diterima dalam 15 detik")

print(
    f"Terhubung: system={connection.target_system}, "
    f"component={connection.target_component}"
)

latest = {}
last_status = None
last_display = 0.0

try:
    while True:
        message = connection.recv_match(
            type=MESSAGE_TYPES,
            blocking=True,
            timeout=0.2,
        )

        if message is not None:
            message_type = message.get_type()
            latest[message_type] = message

            if message_type == "STATUSTEXT":
                text = str(field(message, "text", "")).rstrip("\x00")
                severity = field(message, "severity", 6)

                last_status = {
                    "severity": SEVERITY.get(severity, str(severity)),
                    "text": text,
                }

        now = time.monotonic()

        if now - last_display >= DISPLAY_INTERVAL:
            display(latest, connection, last_status)
            last_display = now

except KeyboardInterrupt:
    print("\nMAVLink dihentikan.")

finally:
    connection.close()