// ============================================================================
// CONFIGURATION — ubah hanya bagian ini saat alamat server berubah.
// ============================================================================
const LOCAL_IP_ROBOT = "192.168.0.4";
const DOMAIN_ROBOT   = "robot.neiaozora.my.id";   // tambahan fallback domain
const SERVER_HOST = location.protocol === "file:" ? LOCAL_IP_ROBOT : location.hostname;
const WS_PORT = 8765;
const HTTP_PORT = 8766;
const HALAMAN_HTTPS = location.protocol === "https:";
const RECONNECT_DELAY_MS = 1000;
const CONNECTION_TIMEOUT_MS = 2000;
const LOCAL_STATE_STALE_MS = 3000;
const DEBUG_ACTIVE = true;
const disableInput = true;
const disableLocal = true;
let kunciHeadingKompas = true;
const MQTT_LIBRARY_URL = "https://unpkg.com/mqtt@5/dist/mqtt.min.js";
const KUNCI_DISABLE_LOCAL = "asv-disable-local-state";
const MAP_CENTER = [-7.069219, 110.304997];
const TRACKS = ["A", "B"];
const MAP_MAX_ZOOM = 22;
const OSM_MAX_NATIVE_ZOOM = 19;
const GOOGLE_MAX_NATIVE_ZOOM = 20;
const pakaiGoogleSatellite = false;

const MQTT_CONFIG = Object.freeze({
    url: "wss://b786a44b5790491898b3c676180e7862.s1.eu.hivemq.cloud:8884/mqtt",
    username: "noxindocraft",
    password: "Zancraft1&"
});

const MQTT_TOPICS = Object.freeze({
    state: "/sistem_broadcast/state_dan_variabel"
});

const LOCAL_STATE_TOPIC = "/local_scope/gui/state";

// WebSocket robot hanya berada di LAN. Cloud memakai MQTT melalui WSS HiveMQ.
const SERVER_HOSTS = [...new Set([LOCAL_IP_ROBOT, SERVER_HOST])]
    .filter(host => host && host !== DOMAIN_ROBOT);
const WS_URLS = SERVER_HOSTS
    .map(host => ({ host, url: `ws://${host}:${WS_PORT}` }));

const CLOUD_HTTP_BASE_URL = `https://${DOMAIN_ROBOT}`;
let HTTP_BASE_URL = HALAMAN_HTTPS
    ? CLOUD_HTTP_BASE_URL
    : `http://${LOCAL_IP_ROBOT}:${HTTP_PORT}`;
let labelHttpAktif = HALAMAN_HTTPS ? `Cloud ${DOMAIN_ROBOT}` : `Local ${LOCAL_IP_ROBOT}`;

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
let mqttClient = null;
let mqttConnected = false;
let mqttStarting = false;
let mqttLibraryPromise = null;
let lastLocalStateAt = 0;
let dataSocketOpenedAt = 0;
let stateMqttTerakhir = null;
let lokalDinonaktifkan = HALAMAN_HTTPS || bacaPilihanDisableLocal();
const photoRetryAt = { atas: 0, bawah: 0 };

// Map & Visualization Layers
let map = null;
let boatMarker = null;
let boatIcon = null;
let boatHeading = 0;
let missionRouteLine = null;
let trajectoryLine = null;
let arenaLayers = [];
let waypointMarkers = [];
let activeWpCircle = null;
let hasCenteredOnBoat = false;
let lastRenderedWpSignature = "";
let lastRenderedCurrentWp = -1;
let lastTrajectorySignature = "";
let lastArenaSignature = "";

// Compass
let compassReady = false;
let compassLastNormalized = 0;
let compassContinuousAngle = 0;

const byId = id => document.getElementById(id);
const number = (value, fallback = 0) => Number.isFinite(Number(value)) ? Number(value) : fallback;
const fixed = (value, digits = 2) => number(value).toFixed(digits);

function tampilkanInputDinonaktifkan() {
    alert("Maaf, client control dimatikan");
}

function pasangPenjagaInput() {
    if (!disableInput) return;
    const kontrolDiizinkan = new Set([
        "disableLocalToggle",
        "kunciHeadingKompasToggle",
        "recenterMapBtn",
        "clearTrailBtn"
    ]);

    document.addEventListener("click", event => {
        const kontrol = event.target.closest("button, input, select, textarea");
        if (!kontrol || kontrolDiizinkan.has(kontrol.id)) return;
        event.preventDefault();
        event.stopImmediatePropagation();
        tampilkanInputDinonaktifkan();
    }, true);
}

function bacaPilihanDisableLocal() {
    try {
        return localStorage.getItem(KUNCI_DISABLE_LOCAL) === "1";
    } catch (_error) {
        return false;
    }
}

function simpanPilihanDisableLocal() {
    try {
        localStorage.setItem(KUNCI_DISABLE_LOCAL, lokalDinonaktifkan ? "1" : "0");
    } catch (_error) {
        debug("SOURCE", "local_storage_unavailable");
    }
}

function debug(channel, event, detail) {
    if (!DEBUG_ACTIVE) return;
    const time = new Date().toISOString();
    console.debug(`[${time}][DEBUG][${channel}] ${event}`, detail ?? "");
}

function getHeadingDegrees() {
    const posisiArena = state.arena && state.arena.posisi_sekarang;
    if (posisiArena && Number.isFinite(Number(posisiArena.heading))) {
        return number(posisiArena.heading);
    }
    const yawRadians = number(state.orientation.z);
    const yawDegrees = yawRadians * 180 / Math.PI;
    return ((yawDegrees % 360) + 360) % 360;
}

function isTelemetryValid(data) {
    if (!data || typeof data !== "object" || Array.isArray(data)) return false;
    return [
        "position", "orientation", "linear", "angular", "battery1",
        "thrusterPort", "thrusterStar", "gps", "mission", "sensors", "detection"
    ].every(key => data[key] && typeof data[key] === "object");
}

function isLocalStateActive() {
    if (lokalDinonaktifkan) return false;
    return Boolean(
        dataSocket &&
        dataSocket.readyState === WebSocket.OPEN &&
        Date.now() - lastLocalStateAt <= LOCAL_STATE_STALE_MS
    );
}

function applyTelemetry(data) {
    if (lokalDinonaktifkan) {
        debug("WS-DATA", "ignored (local disabled)");
        return;
    }
    if (!isTelemetryValid(data)) {
        debug("WS-DATA", "invalid_state_schema", data);
        return;
    }
    debug("WS-DATA", "state_received", data);
    lastLocalStateAt = Date.now();
    HTTP_BASE_URL = `http://${activeServerHost}:${HTTP_PORT}`;
    labelHttpAktif = `Local ${activeServerHost}`;
    state = data;
    setConnection(true, `Local ${activeServerHost}`);
    render();
}

// ─── Fungsi untuk menerapkan state dari MQTT (fallback) ──────────────────
function applyMqttState(data) {
    if (!isTelemetryValid(data)) {
        debug("MQTT-STATE", "invalid_state_schema", data);
        return;
    }
    stateMqttTerakhir = data;
    if (isLocalStateActive()) {
        debug("MQTT-STATE", "ignored (WS active)");
        return;
    }
    debug("MQTT-STATE", lokalDinonaktifkan ? "applied (cloud forced)" : "applied as fallback", data);
    HTTP_BASE_URL = CLOUD_HTTP_BASE_URL;
    labelHttpAktif = `Cloud ${DOMAIN_ROBOT}`;
    state = data;
    setConnection(true, lokalDinonaktifkan ? "Cloud MQTT (Local disabled)" : "Cloud MQTT fallback");
    render();
}

// ─── HTTP Photo Loader ─────────────────────────────────────────────────────
function updatePhotoElement(camera) {
    const img = byId(`${camera}CamImg`);
    if (!img) return;

    const readyKey = `foto_${camera}_ready`;
    const foto = state && state.foto && state.foto[camera];
    const isReady = foto
        ? foto.tersedia === true
        : state && state.detection && state.detection[readyKey] === true;
    const revision = foto ? number(foto.revisi) : (isReady ? 1 : 0);
    const signature = `${HTTP_BASE_URL}:${isReady}:${revision}`;

    if (img.dataset.photoSignature === signature) {
        return;
    }
    if (isReady && Date.now() < photoRetryAt[camera]) {
        return;
    }

    if (isReady && HTTP_BASE_URL) {
        const url = `${HTTP_BASE_URL}/foto/${camera}.jpg?v=${revision}`;
        img.dataset.photoSignature = signature;
        img.onload = () => {
            photoRetryAt[camera] = 0;
            setPhotoConnection(true, labelHttpAktif);
        };
        img.onerror = () => {
            img.dataset.photoSignature = "";
            photoRetryAt[camera] = Date.now() + 3000;
            setPhotoConnection(false, "Foto HTTP belum tersedia");
        };
        img.src = url;
        img.alt = `Foto ${camera}`;
        debug("HTTP-PHOTO", `set ${camera}`, { url });
    } else {
        img.dataset.photoSignature = signature;
        if (!img.src.endsWith("camera-placeholder.png")) {
            img.src = "camera-placeholder.png";
            img.alt = `Foto ${camera} (belum tersedia)`;
        }
    }
}

function connectDataWebSocket() {
    clearTimeout(dataReconnectTimer);
    clearTimeout(dataConnectionTimer);
    if (lokalDinonaktifkan) {
        debug("WS-DATA", "connection_skipped (local disabled)");
        return;
    }

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
        lastLocalStateAt = 0;
        dataSocketOpenedAt = Date.now();
        setConnection(false, `Menunggu state ${target.host}`);
        const subscription = {
            aksi: "berlangganan",
            topik: LOCAL_STATE_TOPIC
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
            if (data.aksi === "pesan") {
                if (data.topik === LOCAL_STATE_TOPIC) applyTelemetry(data.data);
                return;
            }
            if (data.aksi === "galat") {
                debug("WS-DATA", "broker_error", data.pesan);
                return;
            }
            if (data.type) {
                debug("WS-DATA", "control_ignored", data.type);
                return;
            }
            // Kompatibilitas read-only dengan server YOLOCenter lama.
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
        lastLocalStateAt = 0;
        dataSocketOpenedAt = 0;
        debug("WS-DATA", "disconnected", { code: event.code, reason: event.reason });
        if (lokalDinonaktifkan) return;
        setConnection(false, "Mencari server data");
        dataReconnectTimer = setTimeout(connectDataWebSocket, RECONNECT_DELAY_MS);
    };
}

function perbaruiToggleSumber() {
    const toggle = byId("disableLocalToggle");
    const pembungkus = byId("disableLocalControl");
    if (toggle) {
        toggle.checked = lokalDinonaktifkan;
        toggle.disabled = disableLocal;
    }
    if (pembungkus) pembungkus.classList.toggle("active", lokalDinonaktifkan);
    if (pembungkus && disableLocal) {
        pembungkus.title = "Checkbox Disable Local dimatikan dari konfigurasi dashboard.js";
    } else if (pembungkus && HALAMAN_HTTPS) {
        pembungkus.title = "Halaman HTTPS wajib memakai cloud; browser memblokir koneksi lokal tanpa TLS";
    }
}

function aturDisableLocal(dinonaktifkan) {
    lokalDinonaktifkan = HALAMAN_HTTPS || Boolean(dinonaktifkan);
    simpanPilihanDisableLocal();
    perbaruiToggleSumber();
    lastLocalStateAt = 0;
    dataSocketOpenedAt = 0;

    if (lokalDinonaktifkan) {
        clearTimeout(dataReconnectTimer);
        clearTimeout(dataConnectionTimer);
        const socketLama = dataSocket;
        dataSocket = null;
        if (socketLama && socketLama.readyState < WebSocket.CLOSING) {
            socketLama.close(1000, "Local dinonaktifkan operator");
        }
        if (stateMqttTerakhir) {
            applyMqttState(stateMqttTerakhir);
        } else {
            setConnection(false, "Cloud MQTT: menunggu state");
        }
        connectMqttState();
        return;
    }

    setConnection(false, "Mencari server data lokal");
    if (stateMqttTerakhir) applyMqttState(stateMqttTerakhir);
    connectDataWebSocket();
}

// ─── MQTT hanya untuk fallback state ───────────────────────────────────
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

async function connectMqttState() {
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
            if (lokalDinonaktifkan && !stateMqttTerakhir) {
                setConnection(false, "Cloud MQTT: menunggu state");
            }
            mqttClient.subscribe(MQTT_TOPICS.state, { qos: 0 }, err => {
                if (err) debug("MQTT", "state_sub_failed", err);
                else debug("MQTT", "subscribed_state");
            });
        });

        mqttClient.on("message", (topic, payload) => {
            try {
                const message = JSON.parse(payload.toString());
                debug("MQTT", "message_received", { topic, bytes: payload.length });
                if (topic === MQTT_TOPICS.state) {
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
            if (!isLocalStateActive()) setConnection(false, "Cloud MQTT offline");
        });
        mqttClient.on("close", () => {
            mqttConnected = false;
            debug("MQTT", "disconnected");
            if (!isLocalStateActive()) setConnection(false, "Cloud MQTT terputus");
        });
        mqttClient.on("error", error => debug("MQTT", "error", { error: error.message }));
    } catch (error) {
        mqttClient = null;
        mqttLibraryPromise = null;
        debug("MQTT", "startup_failed", { error: error.message });
        if (!isLocalStateActive()) setConnection(false, "Cloud MQTT gagal dimuat");
    } finally {
        mqttStarting = false;
    }
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

function monitorLocalState() {
    if (lokalDinonaktifkan) return;
    if (!dataSocket || dataSocket.readyState !== WebSocket.OPEN) return;
    const acuanWaktu = lastLocalStateAt || dataSocketOpenedAt;
    if (acuanWaktu && Date.now() - acuanWaktu > LOCAL_STATE_STALE_MS) {
        debug("WS-DATA", "state_timeout", { host: activeServerHost });
        dataSocket.close();
    }
}

async function sendCommand(command) {
    if (disableInput && command.command !== "clear_history") {
        tampilkanInputDinonaktifkan();
        return null;
    }
    const request = { id: Date.now().toString(36), ...command };

    try {
        debug("HTTP-COMMAND", "request_sent", { url: `${HTTP_BASE_URL}/api/command`, data: request });
        const response = await fetch(`${HTTP_BASE_URL}/api/command`, {
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

// ─── Render utama ─────────────────────────────────────────────────────────
function render() {
    if (!state) return;
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
    updateArenaVisualization();
    updateBoatMarker(heading);
    updateTrajectory();
    updateWaypoints();

    // ─── Update foto via HTTP ─────────────────────────────────────
    updatePhotoElement("atas");
    updatePhotoElement("bawah");
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

    const disableLocalToggle = byId("disableLocalToggle");
    if (disableLocalToggle) {
        perbaruiToggleSumber();
        disableLocalToggle.onchange = () => aturDisableLocal(disableLocalToggle.checked);
    }

    const kunciHeadingToggle = byId("kunciHeadingKompasToggle");
    if (kunciHeadingToggle) {
        kunciHeadingToggle.checked = kunciHeadingKompas;
        kunciHeadingToggle.onchange = () => {
            kunciHeadingKompas = kunciHeadingToggle.checked;
            perbaruiRotasiPeta(boatHeading);
        };
    }

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
            const posisi = posisiPetaSekarang();
            if (posisi) {
                map.panTo([posisi.lat, posisi.lon]);
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

function pasangLayerOsm() {
    RotaMap.tileLayer(
        "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
        { maxNativeZoom: OSM_MAX_NATIVE_ZOOM }
    ).addTo(map);
}

function pasangLayerPeta() {
    if (!pakaiGoogleSatellite) {
        pasangLayerOsm();
        return;
    }

    RotaMap.tileLayer(
        "https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}",
        { maxNativeZoom: GOOGLE_MAX_NATIVE_ZOOM }
    ).addTo(map);
    debug("MAP", "google_satellite_public_active");
}

function initMap() {
    if (typeof RotaMap === "undefined") {
        byId("map").textContent = "RotaMap tidak tersedia";
        return;
    }
    map = RotaMap.map("map", {
        center: MAP_CENTER,
        zoom: 19,
        maxZoom: MAP_MAX_ZOOM,
        minZoom: 14
    });
    pasangLayerPeta();

    missionRouteLine = RotaMap.polyline([], { color: '#f59e0b', weight: 3, dashArray: '6,6', opacity: 0.85 }).addTo(map);
    trajectoryLine = RotaMap.polyline([], { color: '#22d3ee', weight: 3, opacity: 0.9 }).addTo(map);

    boatIcon = RotaMap.divIcon({
        html: '<div style="font-size:26px;line-height:30px;text-align:center;filter:drop-shadow(0 2px 5px rgba(0,0,0,0.6));">⛵</div>',
        iconSize: [30, 30],
        iconAnchor: [15, 15]
    });
    new ResizeObserver(() => map.invalidateSize()).observe(byId("mapContainer"));
}

function updateBoatMarker(heading) {
    if (!map) return;

    const posisi = posisiPetaSekarang();
    if (!posisi) return;
    const { lat, lon } = posisi;

    if (!boatMarker) {
        boatMarker = RotaMap.marker([lat, lon], { icon: boatIcon, rotation: 0 }).addTo(map);
    }
    boatMarker.setLatLng([lat, lon]);
    boatHeading = heading;
    boatMarker.setRotation(boatHeading);
    perbaruiRotasiPeta(boatHeading);

    if (!hasCenteredOnBoat) {
        map.panTo([lat, lon]);
        hasCenteredOnBoat = true;
    }
}

function perbaruiRotasiPeta(heading) {
    if (!map) return;
    map.setBearing(kunciHeadingKompas ? number(heading) : 0);
}

function posisiPetaSekarang() {
    if (!state) return null;
    const posisiArena = state.arena && state.arena.posisi_sekarang;
    if (posisiArena && posisiArena.lat != null && posisiArena.lon != null) {
        return posisiArena;
    }
    return null;
}

function updateTrajectory() {
    if (!trajectoryLine) return;
    const riwayat = state.arena && Array.isArray(state.arena.riwayat_pergerakan)
        ? state.arena.riwayat_pergerakan
        : [];
    const titikTerakhir = riwayat[riwayat.length - 1];
    const signature = `${riwayat.length}:${titikTerakhir ? titikTerakhir.timestamp : ""}`;
    if (signature === lastTrajectorySignature) return;

    const titikPeta = riwayat
        .filter(titik => titik.lat != null && titik.lon != null)
        .map(titik => [titik.lat, titik.lon]);
    trajectoryLine.setLatLngs(titikPeta);
    lastTrajectorySignature = signature;
}

function hapusVisualisasiArena() {
    arenaLayers.forEach(layer => {
        if (layer && typeof layer.remove === "function") layer.remove();
    });
    arenaLayers = [];
}

function titikPetaArena(titik) {
    if (!titik || titik.lat == null || titik.lon == null) return null;
    return [Number(titik.lat), Number(titik.lon)];
}

function tambahTitikArena(titik, warna, radius) {
    const posisi = titikPetaArena(titik);
    if (!posisi) return;
    arenaLayers.push(RotaMap.circle(posisi, {
        radius,
        color: warna,
        fillColor: warna,
        fillOpacity: 0.85,
        weight: 2,
        minRadiusPx: 4
    }).addTo(map));
}

function updateArenaVisualization() {
    if (!map) return;
    const visualisasi = state.arena && state.arena.visualisasi;
    const signature = visualisasi ? JSON.stringify(visualisasi) : "";
    if (signature === lastArenaSignature) return;

    hapusVisualisasiArena();
    lastArenaSignature = signature;
    if (!visualisasi) return;

    const batas = Array.isArray(visualisasi.batas)
        ? visualisasi.batas.map(titikPetaArena).filter(Boolean)
        : [];
    if (batas.length >= 3) {
        arenaLayers.push(RotaMap.polygon(batas, {
            color: "#38bdf8",
            weight: 2,
            fillColor: "#0ea5e9",
            fillOpacity: 0.06,
            dashArray: "8,5"
        }).addTo(map));
    }

    const radiusBuoy = number(
        visualisasi.dimensi && visualisasi.dimensi.radius_buoy,
        0.15
    );
    const warnaBuoy = { merah: "#ef4444", hijau: "#22c55e" };
    Object.entries(visualisasi.buoy || {}).forEach(([warna, daftar]) => {
        (daftar || []).forEach(titik => {
            tambahTitikArena(titik, warnaBuoy[warna] || "#e2e8f0", radiusBuoy);
        });
    });

    (visualisasi.docking || []).forEach(titik => {
        tambahTitikArena(titik, "#f59e0b", radiusBuoy);
    });

    const warnaKotak = {
        merah: "#dc2626",
        hijau: "#16a34a",
        biru: "#2563eb"
    };
    Object.entries(visualisasi.kotak || {}).forEach(([warna, titik]) => {
        tambahTitikArena(titik, warnaKotak[warna] || "#ffffff", 0.35);
    });

    tambahTitikArena(visualisasi.titik_mulai, "#ffffff", 0.5);
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
    pasangPenjagaInput();
    initComponents();
    initMap();
    connectMqttState();
    if (lokalDinonaktifkan) {
        setConnection(false, "Cloud MQTT: menunggu state");
    } else {
        connectDataWebSocket();
    }
    setInterval(monitorLocalState, 1000);
    setInterval(() => byId("timeFooter").textContent = new Date().toLocaleString(), 100);
});
