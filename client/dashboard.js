// ============================================================================
// CONFIGURATION — ubah hanya bagian ini saat alamat server berubah.
// ============================================================================
const LOCAL_IP_ROBOT = "192.168.0.4";
const DOMAIN_ROBOT   = "robot.neiaozora.my.id";   // tambahan fallback domain
const SERVER_HOST = location.protocol === "file:" ? LOCAL_IP_ROBOT : location.hostname;
const WS_PORT = 8765;
const HTTP_PORT = 8766;
const RECONNECT_DELAY_MS = 1000;
const CONNECTION_TIMEOUT_MS = 2000;
const DEBUG_ACTIVE = true;
const MQTT_LIBRARY_URL = "https://unpkg.com/mqtt@5/dist/mqtt.min.js";
const MAP_CENTER = [-7.069219, 110.304997];
const TRACKS = ["A", "B"];

const MQTT_CONFIG = Object.freeze({
    url: "wss://b786a44b5790491898b3c676180e7862.s1.eu.hivemq.cloud:8884/mqtt",
    username: "noxindocraft",
    password: "Zancraft1&"
});

const MQTT_TOPICS = Object.freeze({
    photo: "/sistem_broadcast/foto",
    state: "/sistem_broadcast/state_dan_variabel"   // tambahan untuk state fallback
});

const WS_SCHEME = location.protocol === "https:" ? "wss" : "ws";
const HTTP_SCHEME = location.protocol === "https:" ? "https" : "http";
// Daftar host: local IP → hostname → domain
const SERVER_HOSTS = [...new Set([LOCAL_IP_ROBOT, SERVER_HOST, DOMAIN_ROBOT])];
const WS_URLS = SERVER_HOSTS
    .map(host => ({ host, url: `${WS_SCHEME}://${host}:${WS_PORT}` }));

let state = null;

const SENSOR_IDS = [
    "heartbeat", "eb", "pmb1", "pmb2", "manip",
    "thrusterPort", "thrusterStar", "ocs", "batPort", "batStar"
];

let dataSocket = null;
let dataReconnectTimer = null;
let dataConnectionTimer = null;
let dataWsUrlIndex = 0;
let activeServerHost = SERVER_HOST;
const photoTransfers = new Map();
let mqttClient = null;
let mqttConnected = false;
let mqttStarting = false;
let mqttLibraryPromise = null;

// Map & Visualization Layers
let map = null;
let boatMarker = null;
let boatIcon = null;
let boatHeading = 0;
let missionRouteLine = null;
let waypointMarkers = [];
let activeWpCircle = null;
let hasCenteredOnBoat = false;
let lastRenderedWpSignature = "";
let lastRenderedCurrentWp = -1;

// Compass
let compassReady = false;
let compassLastNormalized = 0;
let compassContinuousAngle = 0;

const byId = id => document.getElementById(id);
const number = (value, fallback = 0) => Number.isFinite(Number(value)) ? Number(value) : fallback;
const fixed = (value, digits = 2) => number(value).toFixed(digits);

function debug(channel, event, detail) {
    if (!DEBUG_ACTIVE) return;
    const time = new Date().toISOString();
    console.debug(`[${time}][DEBUG][${channel}] ${event}`, detail ?? "");
}

function getHeadingDegrees() {
    const yawRadians = number(state.orientation.z);
    const yawDegrees = yawRadians * 180 / Math.PI;
    return ((yawDegrees % 360) + 360) % 360;
}

function applyTelemetry(data) {
    if (!data || typeof data !== "object" || Array.isArray(data)) return;
    debug("WS-DATA", "state_received", data);
    state = data;
    render();
}

// ─── Fungsi untuk menerapkan state dari MQTT (fallback) ──────────────────
function applyMqttState(data) {
    if (!data || typeof data !== "object" || Array.isArray(data)) return;
    // Hanya pakai jika WebSocket belum terhubung
    if (dataSocket && dataSocket.readyState === WebSocket.OPEN) {
        debug("MQTT-STATE", "ignored (WS active)");
        return;
    }
    debug("MQTT-STATE", "applied as fallback", data);
    state = data;
    render();
}

function connectDataWebSocket() {
    clearTimeout(dataReconnectTimer);
    clearTimeout(dataConnectionTimer);

    const target = WS_URLS[dataWsUrlIndex % WS_URLS.length];
    dataWsUrlIndex += 1;

    const newSocket = new WebSocket(target.url);
    dataSocket = newSocket;
    debug("WS-DATA", "connecting", target);
    setConnection(false, `Menghubungkan ${target.host}`);

    dataConnectionTimer = setTimeout(() => {
        if (newSocket.readyState === WebSocket.CONNECTING) newSocket.close();
    }, CONNECTION_TIMEOUT_MS);

    newSocket.onopen = () => {
        if (dataSocket !== newSocket) return;
        clearTimeout(dataConnectionTimer);
        activeServerHost = target.host;
        setConnection(true, `Connected ${target.host}`);
        const subscription = {
            type: "subscribe",
            component: "dashboard-data",
            state: true,
            camera: false,
            photos: false,
            state_hz: 30
        };
        debug("WS-DATA", "connected", target);
        debug("WS-DATA", "subscription_sent", subscription);
        newSocket.send(JSON.stringify(subscription));
    };

    newSocket.onmessage = event => {
        if (dataSocket !== newSocket) return;
        if (typeof event.data !== "string") {
            debug("WS-DATA", "binary_ignored", { bytes: event.data.size });
            return;
        }
        try {
            const data = JSON.parse(event.data);
            if (data.type) {
                debug("WS-DATA", "control_received", data);
                return;
            }
            applyTelemetry(data);
        } catch (error) {
            debug("WS-DATA", "invalid_payload", { payload: event.data, error: error.message });
            console.error("Payload data WebSocket tidak valid", error);
        }
    };

    newSocket.onerror = event => {
        debug("WS-DATA", "socket_error", event.type);
        newSocket.close();
    };
    newSocket.onclose = event => {
        if (dataSocket !== newSocket) return;
        clearTimeout(dataConnectionTimer);
        debug("WS-DATA", "disconnected", { code: event.code, reason: event.reason });
        setConnection(false, "Mencari server data");
        dataReconnectTimer = setTimeout(connectDataWebSocket, RECONNECT_DELAY_MS);
    };
}

function processPhotoMessage(message) {
    const channel = "MQTT-PHOTO";
    debug(channel, "message_received", photoDebugDetail(message));
    if (message.type === "photo_status") {
        const ready = Boolean(message.atas || message.bawah);
        if (!message.atas) byId("atasCamImg").src = "camera-placeholder.png";
        if (!message.bawah) byId("bawahCamImg").src = "camera-placeholder.png";
        setPhotoConnection(ready, ready ? "Camera Ready" : "Menunggu Target...");
        return;
    }
    if (message.type === "photo_start") {
        if (!['atas', 'bawah'].includes(message.camera)) return;
        const totalChunks = number(message.total_chunks);
        if (totalChunks < 1 || totalChunks > 10000) return;
        photoTransfers.set(message.transfer_id, {
            camera: message.camera,
            channel,
            mimeType: message.mime_type || "image/jpeg",
            totalBytes: number(message.total_bytes),
            totalChars: number(message.total_chars),
            sha256: message.sha256,
            chunks: new Array(totalChunks)
        });
        debug(channel, "transfer_started", photoDebugDetail(message));
        return;
    }
    if (message.type === "photo_chunk") {
        const transfer = photoTransfers.get(message.transfer_id);
        const index = number(message.index, -1);
        if (!transfer || index < 0 || index >= transfer.chunks.length || typeof message.data !== "string") return;
        transfer.chunks[index] = message.data;
        debug(transfer.channel, "chunk_stored", photoDebugDetail(message));
        return;
    }
    if (message.type === "photo_end") {
        finishPhotoTransfer(message.transfer_id);
        return;
    }
    debug(channel, "unknown_message", photoDebugDetail(message));
}

function loadMqttLibrary() {
    if (window.mqtt) return Promise.resolve(window.mqtt);
    if (mqttLibraryPromise) return mqttLibraryPromise;

    mqttLibraryPromise = new Promise((resolve, reject) => {
        const script = document.createElement("script");
        const timeout = setTimeout(() => reject(new Error("Waktu muat MQTT.js habis")), 10000);
        script.src = MQTT_LIBRARY_URL;
        script.onload = () => {
            clearTimeout(timeout);
            window.mqtt ? resolve(window.mqtt) : reject(new Error("MQTT.js tidak tersedia"));
        };
        script.onerror = () => {
            clearTimeout(timeout);
            reject(new Error("Gagal memuat MQTT.js"));
        };
        document.head.appendChild(script);
    });
    return mqttLibraryPromise;
}

async function connectMqttPhoto() {
    if (mqttClient || mqttStarting) return;
    mqttStarting = true;
    debug("MQTT", "connecting", { url: MQTT_CONFIG.url });

    try {
        const mqtt = await loadMqttLibrary();
        const randomId = window.crypto && window.crypto.randomUUID
            ? window.crypto.randomUUID().slice(0, 8)
            : Math.random().toString(16).slice(2, 10);
        mqttClient = mqtt.connect(MQTT_CONFIG.url, {
            username: MQTT_CONFIG.username,
            password: MQTT_CONFIG.password,
            clientId: `dashboard-${randomId}`,
            protocolVersion: 4,
            clean: true,
            connectTimeout: 5000,
            reconnectPeriod: 3000,
            keepalive: 30
        });

        mqttClient.on("connect", () => {
            mqttConnected = true;
            debug("MQTT", "connected", { url: MQTT_CONFIG.url });
            // Subscribe ke kedua topik
            mqttClient.subscribe(MQTT_TOPICS.photo, { qos: 0 }, err => {
                if (err) debug("MQTT", "photo_sub_failed", err);
                else debug("MQTT", "subscribed_photo");
            });
            mqttClient.subscribe(MQTT_TOPICS.state, { qos: 0 }, err => {
                if (err) debug("MQTT", "state_sub_failed", err);
                else debug("MQTT", "subscribed_state");
            });
            setPhotoConnection(true, "Cloud HiveMQ");
        });

        mqttClient.on("message", (topic, payload) => {
            try {
                const message = JSON.parse(payload.toString());
                debug("MQTT", "message_received", { topic, bytes: payload.length });

                if (topic === MQTT_TOPICS.photo) {
                    processPhotoMessage(message);
                } else if (topic === MQTT_TOPICS.state) {
                    applyMqttState(message);
                }
            } catch (error) {
                debug("MQTT", "invalid_payload", { topic, error: error.message });
            }
        });

        mqttClient.on("reconnect", () => debug("MQTT", "reconnecting"));
        mqttClient.on("offline", () => {
            mqttConnected = false;
            debug("MQTT", "offline");
        });
        mqttClient.on("close", () => {
            mqttConnected = false;
            debug("MQTT", "disconnected");
        });
        mqttClient.on("error", error => debug("MQTT", "error", { error: error.message }));
    } catch (error) {
        mqttClient = null;
        mqttLibraryPromise = null;
        debug("MQTT", "startup_failed", { error: error.message });
    } finally {
        mqttStarting = false;
    }
}

function finishPhotoTransfer(transferId) {
    const transfer = photoTransfers.get(transferId);
    if (!transfer) return;
    if (transfer.chunks.some(chunk => typeof chunk !== "string")) {
        debug(transfer.channel, "transfer_incomplete", { transferId });
        photoTransfers.delete(transferId);
        return;
    }

    const base64 = transfer.chunks.join("");
    if (base64.length !== transfer.totalChars) {
        debug(transfer.channel, "size_mismatch", { transferId, expected: transfer.totalChars, received: base64.length });
        photoTransfers.delete(transferId);
        return;
    }

    const image = byId(`${transfer.camera}CamImg`);
    image.src = `data:${transfer.mimeType};base64,${base64}`;
    image.alt = `Foto kamera ${transfer.camera}`;
    setPhotoConnection(true, "Camera Ready");
    debug(transfer.channel, "image_rendered", {
        camera: transfer.camera,
        transferId,
        bytes: transfer.totalBytes,
        characters: base64.length,
        sha256: transfer.sha256
    });
    photoTransfers.delete(transferId);
}

function photoDebugDetail(message) {
    if (message.type !== "photo_chunk") return message;
    return {
        type: message.type,
        camera: message.camera,
        transfer_id: message.transfer_id,
        index: message.index,
        total_chunks: message.total_chunks,
        characters: typeof message.data === "string" ? message.data.length : 0
    };
}

function setConnection(connected, message) {
    const footer = byId("connFooter");
    footer.textContent = message || (connected ? "Connected" : "Disconnected");
    footer.className = connected ? "blue" : "red";
}

function setPhotoConnection(connected, message) {
    const footer = byId("photoFooter");
    footer.textContent = message;
    footer.className = connected ? "blue" : "red";
}

async function sendCommand(command) {
    const httpUrl = `${HTTP_SCHEME}://${activeServerHost}:${HTTP_PORT}`;
    const request = { id: Date.now().toString(36), ...command };

    try {
        debug("HTTP-COMMAND", "request_sent", { url: `${httpUrl}/api/command`, data: request });
        const response = await fetch(`${httpUrl}/api/command`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(request)
        });
        const result = await response.json();
        debug("HTTP-COMMAND", "response_received", { status: response.status, data: result });
        if (!response.ok || !result.ok) {
            const error = new Error(result.error || `HTTP ${response.status}`);
            error.responsHttp = true;
            throw error;
        }
        return result;
    } catch (error) {
        debug("HTTP-COMMAND", "request_failed", { error: error.message, data: request });
        if (error.responsHttp) {
            console.error("Command HTTP ditolak server", error);
            alert(`Command ditolak server: ${error.message}`);
            return null;
        }
        console.error("Command HTTP gagal", error);
        alert(`Command HTTP gagal: ${error.message}`);
        return null;
    }
}

function render() {
    const heading = getHeadingDegrees();

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

    updateCompass(heading);
    renderDataBoxes(heading);
    updateBoatMarker(heading);
    updateWaypoints();
}

function updateCompass(rawDegrees) {
    if (!Number.isFinite(rawDegrees)) return;

    const normalized = ((rawDegrees % 360) + 360) % 360;
    if (!compassReady) {
        compassReady = true;
        compassContinuousAngle = normalized;
    } else {
        const delta = ((normalized - compassLastNormalized + 540) % 360) - 180;
        compassContinuousAngle += delta;
    }
    compassLastNormalized = normalized;

    const rose = byId("compassRose");
    if (rose) rose.style.transform = `rotate(${compassContinuousAngle}deg)`;
    const val = byId("compassValue");
    if (val) val.textContent = `${normalized.toFixed(1)}°`;
}

function renderDataBoxes(heading) {
    const p = state.position, o = state.orientation, l = state.linear, a = state.angular;
    byId("posBox").innerHTML = `<b>Position</b><br>X: ${fixed(p.x,3)}<br>Y: ${fixed(p.y,3)}<br>Z: ${fixed(p.z,3)}`;
    byId("oriBox").innerHTML = `<b>Orientation</b><br>X: ${fixed(o.x,3)}<br>Y: ${fixed(o.y,3)}<br>Z: ${fixed(o.z,3)}<br>W: ${fixed(o.w,3)}`;
    byId("linBox").innerHTML = `<b>Linear</b><br>X: ${fixed(l.x,3)}<br>Y: ${fixed(l.y,3)}<br>Z: ${fixed(l.z,3)}`;
    byId("angBox").innerHTML = `<b>Angular</b><br>X: ${fixed(a.x,3)}<br>Y: ${fixed(a.y,3)}<br>Z: ${fixed(a.z,3)}`;

    const b = state.battery1, port = state.thrusterPort, star = state.thrusterStar;
    byId("bat1Box").innerHTML = `<b>Battery</b><br>Voltage: ${fixed(b.voltage,1)} V<br>Current: ${fixed(b.current,1)} A<br>Capacity: ${number(b.capacity)} mAh<br>Used: ${fixed(b.used,0)} mAh<br>Temp: ${number(b.temp)}°C`;

    const sogKts = state.gps.sog * 1.94384;
    byId("sogCogBox").innerHTML = `<b>SOG & COG & Heading</b><br>SOG: ${fixed(state.gps.sog,2)} m/s (${fixed(sogKts,2)} kts)<br>COG: ${fixed(state.gps.cog,1)}°<br>Heading: ${fixed(heading,1)}°`;

    byId("thrusterPortBox").innerHTML = `<b>Thrusters (Port)</b><br>Voltage: ${fixed(port.voltage,1)}<br>Current: ${fixed(port.current,1)}<br>Capacity: ${number(port.capacity)}mAh<br>Temperature: ${number(port.temp)}`;
    byId("thrusterStarBox").innerHTML = `<b>Thrusters (Star)</b><br>Voltage: ${fixed(star.voltage,1)}<br>Current: ${fixed(star.current,1)}<br>Capacity: ${number(star.capacity)}mAh<br>Temperature: ${number(star.temp)}`;
}

function initComponents() {
    byId("sensorList").innerHTML = SENSOR_IDS.map(id => `<div class="status-item"><span>${id.toUpperCase()}</span><div id="sensor_${id}" class="status-box">-</div></div>`).join("");
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
        if (state && TRACKS.includes(track) && track !== state.currentTrack && confirm(`Pindah ke Lintasan ${track}?`)) {
            sendCommand({ command: "set_track", track });
        }
    });

    const recenterBtn = byId("recenterMapBtn");
    if (recenterBtn) {
        recenterBtn.onclick = () => {
            if (state && state.gps.lat != null && state.gps.lon != null) {
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

    missionRouteLine = RotaMap.polyline([], { color: '#f59e0b', weight: 3, dashArray: '6,6', opacity: 0.85 }).addTo(map);

    boatIcon = RotaMap.divIcon({
        html: '<div style="font-size:26px;line-height:30px;text-align:center;filter:drop-shadow(0 2px 5px rgba(0,0,0,0.6));">⛵</div>',
        iconSize: [30, 30],
        iconAnchor: [15, 15]
    });
    new ResizeObserver(() => map.invalidateSize()).observe(byId("mapContainer"));
}

function updateBoatMarker(heading) {
    if (!map) return;

    const hasFix = Boolean(state.gps.fix) && state.gps.lat != null && state.gps.lon != null;
    if (!hasFix) return;

    const lat = state.gps.lat;
    const lon = state.gps.lon;

    if (!boatMarker) {
        boatMarker = RotaMap.marker([lat, lon], { icon: boatIcon, rotation: 0 }).addTo(map);
    }
    boatMarker.setLatLng([lat, lon]);
    boatHeading = heading;
    boatMarker.setRotation(boatHeading);

    if (!hasCenteredOnBoat) {
        map.panTo([lat, lon]);
        hasCenteredOnBoat = true;
    }
}

function updateWaypoints() {
    if (!map) return;

    const wpList = (state.mission && Array.isArray(state.mission.waypoints)) ? state.mission.waypoints : [];
    const currentSeq = number(state.mission.current, 0);
    const signature = JSON.stringify(wpList.map(wp => [wp.seq, wp.lat, wp.lon, wp.param2]));

    const shouldRecreate = signature !== lastRenderedWpSignature;
    const activeChanged = (currentSeq !== lastRenderedCurrentWp);

    if (!shouldRecreate && !activeChanged) return;

    if (shouldRecreate) {
        waypointMarkers.forEach(item => {
            if (item.marker && typeof item.marker.remove === "function") item.marker.remove();
        });
        waypointMarkers = [];

        const routePts = [];
        wpList.forEach((wp, idx) => {
            if (wp.lat == null || wp.lon == null) return;
            const pt = [wp.lat, wp.lon];
            const radius = number(wp.param2) > 0 ? number(wp.param2) : 1.5;
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
            marker.bindPopup(`<b>Waypoint #${wp.seq !== undefined ? wp.seq : idx}</b><br>Lat: ${fixed(wp.lat, 6)}<br>Lon: ${fixed(wp.lon, 6)}<br>Radius: ${fixed(radius, 1)} m`);
            waypointMarkers.push({
                marker,
                seq: wp.seq !== undefined ? wp.seq : idx,
                lat: wp.lat,
                lon: wp.lon,
                radius
            });
        });

        if (missionRouteLine) {
            missionRouteLine.setLatLngs(routePts);
        }
        lastRenderedWpSignature = signature;
    } else if (activeChanged) {
        waypointMarkers.forEach(item => {
            const isActive = (item.seq === currentSeq);
            const isHome = (item.seq === 0);
            const el = item.marker._inner && item.marker._inner.firstElementChild;
            if (el) {
                el.className = `wp-badge ${isActive ? 'wp-badge-active' : ''} ${isHome ? 'wp-badge-home' : ''}`;
            }
        });
    }

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
    connectDataWebSocket();
    connectMqttPhoto();
    setInterval(() => byId("timeFooter").textContent = new Date().toLocaleString(), 100);
});