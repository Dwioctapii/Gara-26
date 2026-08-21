// ============================================================================
// CONFIGURATION — ubah hanya bagian ini saat alamat server berubah.
// ============================================================================
const SERVER_HOST = location.protocol === "file:" ? "192.168.0.4" : location.hostname;
const WS_PORT = 8765;
const HTTP_PORT = 8766;
const RECONNECT_DELAY_MS = 3000;
const PHOTO_POLL_MS = 1000;
const MAP_CENTER = [-7.069219, 110.304997];
const TRACKS = ["A", "B"];

const WS_SCHEME = location.protocol === "https:" ? "wss" : "ws";
const HTTP_SCHEME = location.protocol === "https:" ? "https" : "http";
const WS_URL = `${WS_SCHEME}://${SERVER_HOST}:${WS_PORT}`;
const HTTP_URL = `${HTTP_SCHEME}://${SERVER_HOST}:${HTTP_PORT}`;

const state = {
    position: { x: 0, y: 0, z: 0 },
    orientation: { x: 0, y: 0, z: 0, w: 1 },
    linear: { x: 0, y: 0, z: 0 },
    angular: { x: 0, y: 0, z: 0 },
    battery1: { voltage: 0, current: 0, pressure: 0, capacity: 0, used: 0, temp: 0 },
    thrusterPort: { voltage: 0, current: 0, capacity: 0, temp: 0 },
    thrusterStar: { voltage: 0, current: 0, capacity: 0, temp: 0 },
    gps: { sog: 0, cog: 0, lat: null, lon: null, satellites: 0, hdop: 99.9, fix: false, lastCalib: "-" },
    speed: 0,
    depth: 0,
    sensors: {},
    arm: "Disarmed",
    missionState: "IDLE",
    currentTrack: "A",
    mission: { current: 0, total: 0 }
};

const SENSOR_IDS = [
    "heartbeat", "eb", "pmb1", "pmb2", "manip",
    "thrusterPort", "thrusterStar", "ocs", "batPort", "batStar"
];

let socket = null;
let reconnectTimer = null;
let map = null;
let boatMarker = null;
let boatHeading = 0;
let compassReady = false;
let compassLastNormalized = 0;
let compassContinuousAngle = 0;

const byId = id => document.getElementById(id);
const number = (value, fallback = 0) => Number.isFinite(Number(value)) ? Number(value) : fallback;
const fixed = (value, digits = 2) => number(value).toFixed(digits);

function merge(target, source) {
    if (!source || typeof source !== "object") return target;
    Object.entries(source).forEach(([key, value]) => {
        if (value && typeof value === "object" && !Array.isArray(value) && target[key] && typeof target[key] === "object") {
            merge(target[key], value);
        } else {
            target[key] = value;
        }
    });
    return target;
}

function applyTelemetry(data) {
    merge(state, data);
    if (data.x !== undefined) state.position.x = number(data.x);
    if (data.y !== undefined) state.position.y = number(data.y);
    if (data.lat !== undefined) state.gps.lat = number(data.lat, null);
    if (data.lon !== undefined) state.gps.lon = number(data.lon, null);
    if (data.sog !== undefined) state.gps.sog = state.speed = number(data.sog);
    if (data.cog !== undefined) state.gps.cog = number(data.cog);
    if (data.kompas !== undefined) state.orientation.z = number(data.kompas) * Math.PI / 180;
    render();
}

function connectWebSocket() {
    clearTimeout(reconnectTimer);
    socket = new WebSocket(WS_URL);
    socket.onopen = () => setConnection(true);
    socket.onmessage = event => {
        try {
            const data = JSON.parse(event.data);
            if (data.type !== "ack") applyTelemetry(data);
        } catch (error) {
            console.error("Invalid WebSocket payload", error);
        }
    };
    socket.onerror = () => socket.close();
    socket.onclose = () => {
        setConnection(false);
        reconnectTimer = setTimeout(connectWebSocket, RECONNECT_DELAY_MS);
    };
}

function setConnection(connected) {
    const footer = byId("connFooter");
    footer.textContent = connected ? "Connected" : "Disconnected";
    footer.className = connected ? "blue" : "red";
}

function sendCommand(command) {
    if (!socket || socket.readyState !== WebSocket.OPEN) {
        console.warn("Command ditolak: WebSocket belum terhubung", command);
        return;
    }
    socket.send(JSON.stringify({ id: Date.now().toString(36), ...command }));
}

async function pollPhotos() {
    try {
        const response = await fetch(`${HTTP_URL}/status`, { cache: "no-store" });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const available = await response.json();
        const stamp = Date.now();
        if (available.atas) byId("atasCamImg").src = `${HTTP_URL}/atas.jpg?t=${stamp}`;
        if (available.bawah) byId("bawahCamImg").src = `${HTTP_URL}/bawah.jpg?t=${stamp}`;
        const footer = byId("photoFooter");
        footer.textContent = available.atas || available.bawah ? "Camera Ready" : "Menunggu Target...";
        footer.className = available.atas || available.bawah ? "blue" : "red";
    } catch {
        const footer = byId("photoFooter");
        footer.textContent = "HTTP Offline";
        footer.className = "red";
    }
}

function render() {
    byId("xCoord").value = fixed(state.position.x, 3);
    byId("yCoord").value = fixed(state.position.y, 3);
    byId("missionStatusText").textContent = state.missionState;
    byId("asvStatusFooter").textContent = state.missionState;
    byId("currentTrackLabel").textContent = TRACKS.includes(state.currentTrack) ? state.currentTrack : "A";
    byId("currentWp").textContent = `${number(state.mission.current)} / ${number(state.mission.total)}`;
    byId("satellitesCount").value = number(state.gps.satellites);
    byId("hdopValue").value = fixed(state.gps.hdop, 1);
    byId("lastCalibText").textContent = `Last Calibration: ${state.gps.lastCalib || "-"}`;
    byId("depthFooter").textContent = fixed(state.depth, 1);
    byId("speedFooter").textContent = fixed(state.speed, 2);

    const gpsReady = Boolean(state.gps.fix);
    byId("gpsStatus").textContent = gpsReady ? "GPS Fix" : "No Fix";
    byId("gpsStatus").className = `gps-status ${gpsReady ? "good-status" : "bad-status"}`;
    byId("gpsFixFooter").textContent = gpsReady ? "Fix" : "No Fix";
    byId("gpsFixFooter").className = gpsReady ? "blue" : "red";

    document.querySelectorAll("#armGroup button").forEach(button => button.classList.remove("state-active"));
    const armButton = { Armed: "armBtn", Disarmed: "disarmBtn", EStop: "eStopBtn" }[state.arm];
    if (armButton) byId(armButton).classList.add("state-active");
    document.querySelectorAll(".track-btn").forEach(button => button.classList.toggle("active-track", button.dataset.track === state.currentTrack));

    SENSOR_IDS.forEach(id => {
        const element = byId(`sensor_${id}`);
        const ok = Boolean(state.sensors[id]);
        element.textContent = ok ? "OK" : "Not OK";
        element.className = `status-box ${ok ? "ok" : "bad"}`;
    });
    updateCompass(number(state.orientation.z) * 180 / Math.PI);
    renderDataBoxes();
    updateBoatMarker();
}

function updateCompass(rawDegrees) {
    if (!Number.isFinite(rawDegrees)) return;

    const normalized = ((rawDegrees % 360) + 360) % 360;
    if (!compassReady) {
        compassReady = true;
        compassContinuousAngle = normalized;
    } else {
        // Shortest signed difference prevents 359° -> 0° from rotating backward.
        const delta = ((normalized - compassLastNormalized + 540) % 360) - 180;
        compassContinuousAngle += delta;
    }
    compassLastNormalized = normalized;

    byId("compassRose").style.transform = `rotate(${compassContinuousAngle}deg)`;
    byId("compassValue").textContent = `${normalized.toFixed(1)}°`;
}

function renderDataBoxes() {
    const p = state.position, o = state.orientation, l = state.linear, a = state.angular;
    byId("posBox").innerHTML = `<b>Position</b><br>X: ${fixed(p.x,3)}<br>Y: ${fixed(p.y,3)}<br>Z: ${fixed(p.z,3)}`;
    byId("oriBox").innerHTML = `<b>Orientation</b><br>X: ${fixed(o.x,3)}<br>Y: ${fixed(o.y,3)}<br>Z: ${fixed(o.z,3)}<br>W: ${fixed(o.w,3)}`;
    byId("linBox").innerHTML = `<b>Linear</b><br>X: ${fixed(l.x,3)}<br>Y: ${fixed(l.y,3)}<br>Z: ${fixed(l.z,3)}`;
    byId("angBox").innerHTML = `<b>Angular</b><br>X: ${fixed(a.x,3)}<br>Y: ${fixed(a.y,3)}<br>Z: ${fixed(a.z,3)}`;
    const b = state.battery1, port = state.thrusterPort, star = state.thrusterStar;
    byId("bat1Box").innerHTML = `<b>Battery</b><br>Voltage: ${fixed(b.voltage,1)}<br>Current: ${fixed(b.current,1)}<br>Capacity: ${number(b.capacity)}mAh<br>Used: ${fixed(b.used,0)}mAh<br>Temperature: ${number(b.temp)}`;
    byId("sogCogBox").innerHTML = `<b>SOG & COG</b><br>SOG: ${fixed(state.gps.sog,2)} m/s<br>COG: ${fixed(state.gps.cog,1)}°<br>Heading: ${fixed(state.orientation.z*180/Math.PI,1)}°`;
    byId("thrusterPortBox").innerHTML = `<b>Thrusters (Port)</b><br>Voltage: ${fixed(port.voltage,1)}<br>Current: ${fixed(port.current,1)}<br>Capacity: ${number(port.capacity)}mAh<br>Temperature: ${number(port.temp)}`;
    byId("thrusterStarBox").innerHTML = `<b>Thrusters (Star)</b><br>Voltage: ${fixed(star.voltage,1)}<br>Current: ${fixed(star.current,1)}<br>Capacity: ${number(star.capacity)}mAh<br>Temperature: ${number(star.temp)}`;
}

function initComponents() {
    byId("sensorList").innerHTML = SENSOR_IDS.map(id => `<div class="status-item"><span>${id.toUpperCase()}</span><div id="sensor_${id}" class="status-box bad">Not OK</div></div>`).join("");
    byId("dataBoxesGrid1").innerHTML = ["posBox","oriBox","linBox","angBox"].map(id => `<div class="black-box" id="${id}"></div>`).join("");
    byId("dataBoxesGrid2").innerHTML = ["bat1Box","sogCogBox","thrusterPortBox","thrusterStarBox"].map(id => `<div class="black-box" id="${id}"></div>`).join("");
    const commands = {
        armBtn: { command: "arm", action: "arm" },
        disarmBtn: { command: "arm", action: "disarm" },
        eStopBtn: { command: "arm", action: "estop" },
        missionStartBtn: { command: "mission", action: "start" },
        missionPauseBtn: { command: "mission", action: "pause" },
        missionStopBtn: { command: "mission", action: "stop" }
    };
    Object.entries(commands).forEach(([id, command]) => byId(id).onclick = () => sendCommand(command));
    document.querySelectorAll(".track-btn").forEach(button => button.onclick = () => {
        const track = button.dataset.track;
        if (TRACKS.includes(track) && track !== state.currentTrack && confirm(`Pindah ke Lintasan ${track}?`)) {
            sendCommand({ command: "set_track", track });
        }
    });
}

function initMap() {
    if (typeof RotaMap === "undefined") {
        byId("map").textContent = "RotaMap tidak tersedia";
        return;
    }
    map = RotaMap.map("map", { center: MAP_CENTER, zoom: 19, maxZoom: 22, minZoom: 14 });
    RotaMap.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png").addTo(map);
    const icon = RotaMap.divIcon({ html: '<div style="font-size:26px;line-height:30px;text-align:center">⛵</div>', iconSize: [30,30], iconAnchor: [15,15] });
    boatMarker = RotaMap.marker(MAP_CENTER, { icon, rotation: 0 }).addTo(map);
    new ResizeObserver(() => map.invalidateSize()).observe(byId("mapContainer"));
}

function updateBoatMarker() {
    if (!map || !boatMarker || !state.gps.fix || state.gps.lat == null || state.gps.lon == null) return;
    boatMarker.setLatLng([state.gps.lat, state.gps.lon]);
    boatHeading = number(state.orientation.z) * 180 / Math.PI;
    boatMarker.setRotation(boatHeading);
}

window.addEventListener("load", () => {
    initComponents();
    initMap();
    render();
    connectWebSocket();
    pollPhotos();
    setInterval(pollPhotos, PHOTO_POLL_MS);
    setInterval(() => byId("timeFooter").textContent = new Date().toLocaleString(), 1000);
});
