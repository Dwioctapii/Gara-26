// ============================================================================
// CONFIGURATION — ubah hanya bagian ini saat alamat server berubah.
// ============================================================================
const SERVER_HOST = location.protocol === "file:" ? "192.168.0.4" : location.hostname;
const WS_PORT = 8765;
const HTTP_PORT = 8766;
const RECONNECT_DELAY_MS = 3000;
const MAP_CENTER = [-7.069219, 110.304997];
const TRACKS = ["A", "B"];

const WS_SCHEME = location.protocol === "https:" ? "wss" : "ws";
const HTTP_SCHEME = location.protocol === "https:" ? "https" : "http";
const WS_URL = `${WS_SCHEME}://${SERVER_HOST}:${WS_PORT}`;
const HTTP_URL = `${HTTP_SCHEME}://${SERVER_HOST}:${HTTP_PORT}`;

const createDefaultState = () => ({
    position: { x: 0, y: 0, z: 0 },
    orientation: { x: 0, y: 0, z: 0, w: 1 },
    linear: { x: 0, y: 0, z: 0 },
    angular: { x: 0, y: 0, z: 0 },
    battery1: { voltage: 0, current: 0, pressure: 0, capacity: 0, used: 0, temp: 0 },
    thrusterPort: { voltage: 0, current: 0, capacity: 0, temp: 0 },
    thrusterStar: { voltage: 0, current: 0, capacity: 0, temp: 0 },
    gps: { sog: 0, cog: 0, lat: null, lon: null, satellites: 0, hdop: 99.9, fix: false, lastCalib: "-" },
    heading: 0,
    speed: 0,
    depth: 0,
    sensors: {},
    arm: "Disarmed",
    missionState: "IDLE",
    currentTrack: "A",
    mission: { current: 0, total: 0, waypoints: [], revision: 0 },
    photos: { atas: null, bawah: null }
});

let state = createDefaultState();
const renderedPhotos = { atas: undefined, bawah: undefined };

const SENSOR_IDS = [
    "heartbeat", "eb", "pmb1", "pmb2", "manip",
    "thrusterPort", "thrusterStar", "ocs", "batPort", "batStar"
];

let socket = null;
let reconnectTimer = null;

// Map & Visualization Layers
let map = null;
let boatMarker = null;
let boatHeading = 0;
let missionRouteLine = null;
let waypointMarkers = [];
let activeWpCircle = null;
let hasCenteredOnBoat = false;
let lastRenderedWpRevision = -1;
let lastRenderedCurrentWp = -1;

// Compass
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
    const nextState = createDefaultState();
    merge(nextState, data);
    state = nextState;
    if (data.x !== undefined) state.position.x = number(data.x);
    if (data.y !== undefined) state.position.y = number(data.y);
    if (data.lat !== undefined) state.gps.lat = number(data.lat, null);
    if (data.lon !== undefined) state.gps.lon = number(data.lon, null);
    if (data.sog !== undefined) state.gps.sog = state.speed = number(data.sog);
    if (data.cog !== undefined) state.gps.cog = number(data.cog);

    // Patch Heading: Ambil heading eksplisit dari backend, atau hitung dari orientasi yaw (rad -> deg)
    if (data.heading !== undefined && data.heading !== null) {
        state.heading = number(data.heading);
    } else if (data.kompas !== undefined && data.kompas !== null) {
        state.heading = number(data.kompas);
    } else if (state.orientation && state.orientation.z !== undefined) {
        state.heading = ((number(state.orientation.z) * 180 / Math.PI) % 360 + 360) % 360;
    }

    render();
}

function connectWebSocket() {
    clearTimeout(reconnectTimer);
    socket = new WebSocket(WS_URL);
    socket.onopen = () => setConnection(true);
    socket.onmessage = event => {
        try {
            const data = JSON.parse(event.data);
            applyTelemetry(data);
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

async function sendCommand(command) {
    try {
        const response = await fetch(`${HTTP_URL}/api/command`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ id: Date.now().toString(36), ...command })
        });
        const result = await response.json();
        if (!response.ok || !result.ok) throw new Error(result.error || `HTTP ${response.status}`);
        return result;
    } catch (error) {
        console.error("Command HTTP ditolak", error);
        alert(`Command gagal: ${error.message}`);
        return null;
    }
}

function renderPhotos() {
    const photos = state.photos && typeof state.photos === "object" ? state.photos : {};
    ["atas", "bawah"].forEach(camera => {
        const base64 = typeof photos[camera] === "string" ? photos[camera] : null;
        if (renderedPhotos[camera] === base64) return;
        renderedPhotos[camera] = base64;
        byId(`${camera}CamImg`).src = base64
            ? `data:image/jpeg;base64,${base64}`
            : "camera-placeholder.png";
    });

    const ready = Boolean(photos.atas || photos.bawah);
    const footer = byId("photoFooter");
    footer.textContent = ready ? "Camera Ready" : "Menunggu Target...";
    footer.className = ready ? "blue" : "red";
}

function render() {
    renderPhotos();
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
        if (element) {
            const ok = Boolean(state.sensors[id]);
            element.textContent = ok ? "OK" : "Not OK";
            element.className = `status-box ${ok ? "ok" : "bad"}`;
        }
    });

    updateCompass(state.heading);
    renderDataBoxes();
    updateBoatMarker();
    updateWaypoints();
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

    const rose = byId("compassRose");
    if (rose) rose.style.transform = `rotate(${compassContinuousAngle}deg)`;
    const val = byId("compassValue");
    if (val) val.textContent = `${normalized.toFixed(1)}°`;
}

function renderDataBoxes() {
    const p = state.position, o = state.orientation, l = state.linear, a = state.angular;
    byId("posBox").innerHTML = `<b>Position</b><br>X: ${fixed(p.x,3)}<br>Y: ${fixed(p.y,3)}<br>Z: ${fixed(p.z,3)}`;
    byId("oriBox").innerHTML = `<b>Orientation</b><br>X: ${fixed(o.x,3)}<br>Y: ${fixed(o.y,3)}<br>Z: ${fixed(o.z,3)}<br>W: ${fixed(o.w,3)}`;
    byId("linBox").innerHTML = `<b>Linear</b><br>X: ${fixed(l.x,3)}<br>Y: ${fixed(l.y,3)}<br>Z: ${fixed(l.z,3)}`;
    byId("angBox").innerHTML = `<b>Angular</b><br>X: ${fixed(a.x,3)}<br>Y: ${fixed(a.y,3)}<br>Z: ${fixed(a.z,3)}`;

    const b = state.battery1, port = state.thrusterPort, star = state.thrusterStar;
    byId("bat1Box").innerHTML = `<b>Battery</b><br>Voltage: ${fixed(b.voltage,1)} V<br>Current: ${fixed(b.current,1)} A<br>Capacity: ${number(b.capacity)} mAh<br>Used: ${fixed(b.used,0)} mAh<br>Temp: ${number(b.temp)}°C`;

    const sogKts = state.gps.sog * 1.94384;
    byId("sogCogBox").innerHTML = `<b>SOG & COG & Heading</b><br>SOG: ${fixed(state.gps.sog,2)} m/s (${fixed(sogKts,2)} kts)<br>COG: ${fixed(state.gps.cog,1)}°<br>Heading: ${fixed(state.heading,1)}°`;

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
    Object.entries(commands).forEach(([id, command]) => {
        const el = byId(id);
        if (el) el.onclick = () => sendCommand(command);
    });

    document.querySelectorAll(".track-btn").forEach(button => button.onclick = () => {
        const track = button.dataset.track;
        if (TRACKS.includes(track) && track !== state.currentTrack && confirm(`Pindah ke Lintasan ${track}?`)) {
            sendCommand({ command: "set_track", track });
        }
    });

    const recenterBtn = byId("recenterMapBtn");
    if (recenterBtn) {
        recenterBtn.onclick = () => {
            if (state.gps.lat != null && state.gps.lon != null) {
                map.panTo([state.gps.lat, state.gps.lon]);
            } else {
                map.panTo(MAP_CENTER);
            }
        };
    }

    const clearTrailBtn = byId("clearTrailBtn");
    if (clearTrailBtn) {
        clearTrailBtn.textContent = "Reset Server History";
        clearTrailBtn.onclick = () => sendCommand({ command: "clear_history" });
    }
}

function initMap() {
    if (typeof RotaMap === "undefined") {
        byId("map").textContent = "RotaMap tidak tersedia";
        return;
    }
    map = RotaMap.map("map", { center: MAP_CENTER, zoom: 19, maxZoom: 22, minZoom: 14 });
    RotaMap.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png").addTo(map);

    // Polyline untuk rute waypoint (Kuning putus-putus)
    missionRouteLine = RotaMap.polyline([], { color: '#f59e0b', weight: 3, dashArray: '6,6', opacity: 0.85 }).addTo(map);

    // Icon kapal ASV
    const icon = RotaMap.divIcon({
        html: '<div style="font-size:26px;line-height:30px;text-align:center;filter:drop-shadow(0 2px 5px rgba(0,0,0,0.6));">⛵</div>',
        iconSize: [30, 30],
        iconAnchor: [15, 15]
    });
    boatMarker = RotaMap.marker(MAP_CENTER, { icon, rotation: 0 }).addTo(map);
    new ResizeObserver(() => map.invalidateSize()).observe(byId("mapContainer"));
}

function updateBoatMarker() {
    if (!map || !boatMarker) return;

    const hasFix = Boolean(state.gps.fix) && state.gps.lat != null && state.gps.lon != null;
    if (!hasFix) return;

    const lat = state.gps.lat;
    const lon = state.gps.lon;

    boatMarker.setLatLng([lat, lon]);
    boatHeading = state.heading;
    boatMarker.setRotation(boatHeading);

    // Auto center ke posisi kapal saat pertama kali fix
    if (!hasCenteredOnBoat) {
        map.panTo([lat, lon]);
        hasCenteredOnBoat = true;
    }

}

function updateWaypoints() {
    if (!map) return;

    const wpList = (state.mission && Array.isArray(state.mission.waypoints)) ? state.mission.waypoints : [];
    const currentSeq = number(state.mission.current, 0);
    const revision = number(state.mission.revision, 0);

    const shouldRecreate = (revision !== lastRenderedWpRevision) || (wpList.length !== waypointMarkers.length);
    const activeChanged = (currentSeq !== lastRenderedCurrentWp);

    if (!shouldRecreate && !activeChanged) return;

    if (shouldRecreate) {
        // Hapus marker WP yang lama
        waypointMarkers.forEach(item => {
            if (item.marker && typeof item.marker.remove === "function") item.marker.remove();
        });
        waypointMarkers = [];

        const routePts = [];
        wpList.forEach((wp, idx) => {
            if (wp.lat == null || wp.lon == null) return;
            const pt = [wp.lat, wp.lon];
            routePts.push(pt);

            const isHome = (idx === 0 || wp.seq === 0);
            const isActive = (wp.seq === currentSeq);
            const badgeClass = `wp-badge ${isActive ? 'wp-badge-active' : ''} ${isHome ? 'wp-badge-home' : ''}`;
            const label = isHome ? 'H' : (wp.seq !== undefined ? wp.seq : idx);

            const icon = RotaMap.divIcon({
                html: `<div class="${badgeClass}" title="Waypoint #${wp.seq || idx}">${label}</div>`,
                iconSize: [22, 22],
                iconAnchor: [11, 11]
            });

            const marker = RotaMap.marker(pt, { icon, keepUpright: true }).addTo(map);
            marker.bindPopup(`<b>Waypoint #${wp.seq !== undefined ? wp.seq : idx}</b><br>Lat: ${fixed(wp.lat, 6)}<br>Lon: ${fixed(wp.lon, 6)}<br>Radius: ${fixed(wp.acceptanceRadius || 1.5, 1)} m`);
            waypointMarkers.push({
                marker,
                seq: wp.seq !== undefined ? wp.seq : idx,
                lat: wp.lat,
                lon: wp.lon,
                radius: wp.acceptanceRadius || 1.5
            });
        });

        if (missionRouteLine) {
            missionRouteLine.setLatLngs(routePts);
        }
        lastRenderedWpRevision = revision;
    } else if (activeChanged) {
        // Cukup perbarui styling active class pada badge
        waypointMarkers.forEach(item => {
            const isActive = (item.seq === currentSeq);
            const isHome = (item.seq === 0);
            const el = item.marker._inner && item.marker._inner.firstElementChild;
            if (el) {
                el.className = `wp-badge ${isActive ? 'wp-badge-active' : ''} ${isHome ? 'wp-badge-home' : ''}`;
            }
        });
    }

    // Update lingkaran Acceptance Radius untuk target waypoint aktif
    const activeWp = waypointMarkers.find(w => w.seq === currentSeq);
    if (activeWp) {
        if (!activeWpCircle) {
            activeWpCircle = RotaMap.circle([activeWp.lat, activeWp.lon], {
                radius: activeWp.radius,
                color: '#f59e0b',
                fillColor: '#fef08a',
                fillOpacity: 0.25,
                weight: 2,
                dashArray: '4,4'
            }).addTo(map);
        } else {
            activeWpCircle.setLatLng([activeWp.lat, activeWp.lon]);
            activeWpCircle.setRadius(activeWp.radius);
        }
    }

    lastRenderedCurrentWp = currentSeq;
}

window.addEventListener("load", () => {
    initComponents();
    initMap();
    render();
    connectWebSocket();
    setInterval(() => byId("timeFooter").textContent = new Date().toLocaleString(), 500);
});
