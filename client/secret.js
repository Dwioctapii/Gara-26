const DOMAIN_ROBOT = "robot.neiaozora.my.id";
const PORT_HTTP_ROBOT = 8766;
const PORT_WS_ROBOT = 8765;
const TOPIK_STATE_LOKAL = "/local_scope/gui/state";
const TOPIK_STATE_CLOUD = "/sistem_broadcast/state_dan_variabel";
const URL_LIBRARY_MQTT = "https://unpkg.com/mqtt@5/dist/mqtt.min.js";

const MQTT_CONFIG = Object.freeze({
    url: "wss://b786a44b5790491898b3c676180e7862.s1.eu.hivemq.cloud:8884/mqtt",
    username: "noxindocraft",
    password: "Zancraft1&",
});

const olehId = id => document.getElementById(id);
let stateBackend = null;
let waktuStateTerakhir = 0;
let soketState = null;
let klienMqtt = null;
let janjiLibraryMqtt = null;
let timerHubungUlang = null;
let versiKoneksi = 0;
let konfirmasiMenunggu = [];

function gunakanCloud() {
    const pilihan = olehId("sumberApi").value;
    return pilihan === "cloud" || (pilihan === "otomatis" && location.protocol === "https:");
}

function alamatDasarApi() {
    if (gunakanCloud()) return `https://${DOMAIN_ROBOT}`;
    return `http://${olehId("ipLokal").value.trim()}:${PORT_HTTP_ROBOT}`;
}

function ubahStatus(id, teks, kelas) {
    const elemen = olehId(id);
    elemen.textContent = teks;
    elemen.className = `status ${kelas}`;
}

function tampilkanStatusAksi(teks, kelas = "") {
    const elemen = olehId("statusAksi");
    elemen.textContent = teks;
    elemen.className = `status-aksi ${kelas}`.trim();
}

function catat(judul, data, berhasil = true) {
    const waktu = new Date().toLocaleTimeString();
    const isi = typeof data === "string" ? data : JSON.stringify(data, null, 2);
    const log = olehId("logRespons");
    log.textContent = `[${waktu}] ${judul}\n${isi}\n\n${log.textContent}`;
    log.style.color = berhasil ? "#a7f3d0" : "#fecaca";
}

function stateValid(data) {
    return data && typeof data === "object" && !Array.isArray(data)
        && data.gps && data.mission && data.pid_config && data.foto && data.arena;
}

function teksKoordinat(titik) {
    if (!titik || titik.lat == null || titik.lon == null) return "Belum ada";
    return `${Number(titik.lat).toFixed(6)}, ${Number(titik.lon).toFixed(6)}`;
}

function statusFoto(foto) {
    if (!foto) return "-";
    return `${foto.tersedia ? "TERSEDIA" : "Kosong"} · rev ${Number(foto.revisi || 0)}`;
}

function perintahSedangAktif(perintah, data) {
    const mode = String(data.mode || "").toUpperCase();
    const statusMisi = String(data.missionState || "").toUpperCase();
    if (perintah.command === "arm" && perintah.action === "arm") return data.arm === "Armed";
    if (perintah.command === "arm" && perintah.action === "disarm") return data.arm === "Disarmed";
    if (perintah.command === "set_mode") return mode === perintah.mode.toUpperCase();
    if (perintah.command === "hold_position") return ["HOLD", "LOITER"].includes(mode);
    if (perintah.command === "go_home") return mode === "RTL";
    if (perintah.command === "set_track") return data.currentTrack === perintah.track;
    if (perintah.command === "logger") return Boolean(data.loggerActive) === (perintah.action === "start");
    if (perintah.command === "mission") {
        return statusMisi === { start: "RUNNING", pause: "PAUSED", stop: "STOPPED" }[perintah.action];
    }
    if (perintah.command === "reset_mission") return statusMisi === "IDLE";
    return false;
}

function renderState() {
    if (!stateBackend) return;
    const data = stateBackend;
    const arena = data.arena || {};
    const foto = data.foto || {};
    const pid = data.pid_config || {};
    const jumlahRiwayat = Array.isArray(arena.riwayat_pergerakan)
        ? arena.riwayat_pergerakan.length
        : 0;

    olehId("nilaiMavlink").textContent = data.connected ? "TERHUBUNG" : "TERPUTUS";
    olehId("nilaiArm").textContent = data.arm || "-";
    olehId("nilaiMode").textContent = data.mode || "-";
    olehId("nilaiMisi").textContent = data.missionState || "-";
    olehId("nilaiArena").textContent = `${data.currentTrack || "-"} · ${arena.status || "belum dimulai"}`;
    olehId("nilaiGps").textContent = `${data.gps.fix ? "FIX" : "NO FIX"} · ${teksKoordinat(data.gps)}`;
    olehId("nilaiHome").textContent = teksKoordinat(data.home);
    olehId("nilaiLogger").textContent = data.loggerActive ? "AKTIF" : "MATI";
    olehId("nilaiTahanFoto").textContent = data.tahan_foto ? "YA" : "TIDAK";
    olehId("nilaiFotoAtas").textContent = statusFoto(foto.atas);
    olehId("nilaiFotoBawah").textContent = statusFoto(foto.bawah);
    olehId("nilaiTrajectory").textContent = `${jumlahRiwayat} titik`;
    olehId("nilaiPid").textContent = `Kp ${pid.kp} · Ki ${pid.ki} · Kd ${pid.kd} · deadband ${pid.deadband} · limit ${pid.integral_limit}`;
    olehId("stateMentah").textContent = JSON.stringify(data, null, 2);

    document.querySelectorAll("[data-perintah]").forEach(tombol => {
        const perintah = JSON.parse(tombol.dataset.perintah);
        tombol.classList.toggle("aktif", perintahSedangAktif(perintah, data));
    });
    document.querySelectorAll("[data-rahasia^='tahan_foto']").forEach(tombol => {
        const ditahan = tombol.dataset.rahasia.endsWith("true");
        tombol.classList.toggle("aktif", Boolean(data.tahan_foto) === ditahan);
    });

    for (const nama of "kp,ki,kd,deadband,integral_limit".split(",")) {
        const masukan = document.querySelector(`#formPid [name="${nama}"]`);
        if (document.activeElement !== masukan && pid[nama] != null) masukan.value = pid[nama];
    }
    cekKonfirmasiState();
}

function terapkanState(data, sumber) {
    if (!stateValid(data)) {
        catat("STATE DITOLAK", "Skema broadcast tidak lengkap", false);
        return;
    }
    stateBackend = data;
    waktuStateTerakhir = Date.now();
    olehId("sumberState").textContent = `${sumber} · ${new Date().toLocaleTimeString()}`;
    ubahStatus("statusState", "State tersambung", "hidup");
    renderState();
}

function buatPemeriksaPerintah(perintah) {
    if (perintah.command === "set_pid") {
        return data => ["kp", "ki", "kd", "deadband", "integral_limit"]
            .every(nama => Number(data.pid_config[nama]) === Number(perintah[nama]));
    }
    if (perintah.command === "set_home") {
        const homeAwal = JSON.stringify(stateBackend && stateBackend.home);
        return data => Boolean(data.home) && JSON.stringify(data.home) !== homeAwal;
    }
    if (perintah.command === "clear_history") {
        return data => Array.isArray(data.arena && data.arena.riwayat_pergerakan)
            && data.arena.riwayat_pergerakan.length === 0;
    }
    if (perintah.command === "calibration") {
        const nilaiAwal = stateBackend && stateBackend.gps.lastCalib;
        return data => data.gps.lastCalib && data.gps.lastCalib !== nilaiAwal;
    }
    const perintahTerpantau = [
        "arm", "set_mode", "hold_position", "go_home",
        "mission", "reset_mission", "set_track", "logger",
    ];
    if (perintahTerpantau.includes(perintah.command)) {
        if (perintah.command === "arm" && perintah.action === "estop") {
            return data => data.arm === "Disarmed";
        }
        return data => perintahSedangAktif(perintah, data);
    }
    return null;
}

function buatPemeriksaRahasia(parameter) {
    if (parameter.startsWith("tahan_foto=")) {
        const nilai = parameter.endsWith("true");
        return data => Boolean(data.tahan_foto) === nilai;
    }
    if (parameter.startsWith("foto_sekarang=")) {
        const kamera = parameter.split("=")[1];
        const fotoAwal = stateBackend && stateBackend.foto && stateBackend.foto[kamera];
        const revisiAwal = Number(fotoAwal && fotoAwal.revisi || 0);
        return data => Number(data.foto[kamera].revisi || 0) > revisiAwal
            && data.foto[kamera].tersedia === true;
    }
    if (parameter.startsWith("reset_foto=")) {
        return data => ["atas", "bawah"].every(kamera => data.foto[kamera].tersedia === false);
    }
    return null;
}

function tungguKonfirmasi(label, pemeriksa) {
    if (!pemeriksa) {
        tampilkanStatusAksi(`${label}: diterima server, tidak memiliki nilai state pembanding.`, "berhasil");
        return;
    }
    konfirmasiMenunggu.push({ label, pemeriksa, batas: Date.now() + 10000 });
    tampilkanStatusAksi(`${label}: masuk antrean, menunggu state backend...`, "menunggu");
    cekKonfirmasiState();
}

function cekKonfirmasiState() {
    if (!konfirmasiMenunggu.length) return;
    const sekarang = Date.now();
    const tersisa = [];
    for (const item of konfirmasiMenunggu) {
        if (stateBackend && item.pemeriksa(stateBackend)) {
            catat("STATE TERKONFIRMASI", item.label);
            tampilkanStatusAksi(`${item.label}: berhasil dikonfirmasi dari broadcast.`, "berhasil");
        } else if (sekarang >= item.batas) {
            const alasan = stateBackend ? "state tidak berubah" : "broadcast state tidak tersambung";
            catat("BELUM TERKONFIRMASI", `${item.label}: ${alasan} dalam 10 detik`, false);
            tampilkanStatusAksi(`${item.label}: belum terkonfirmasi dalam 10 detik.`, "gagal");
        } else {
            tersisa.push(item);
        }
    }
    konfirmasiMenunggu = tersisa;
}

async function mintaJson(jalur, opsi = {}) {
    const respons = await fetch(`${alamatDasarApi()}${jalur}`, opsi);
    const teks = await respons.text();
    let isi;
    try {
        isi = JSON.parse(teks);
    } catch (_galat) {
        isi = { teks };
    }
    if (!respons.ok || isi.ok === false) throw new Error(isi.error || `HTTP ${respons.status}`);
    return isi;
}

async function jalankan(tombol, pekerjaan) {
    tombol.disabled = true;
    tombol.classList.remove("terkirim", "gagal");
    try {
        const dijalankan = await pekerjaan();
        if (dijalankan !== false) tombol.classList.add("terkirim");
    } catch (galat) {
        tombol.classList.add("gagal");
        tampilkanStatusAksi(galat.message, "gagal");
        catat("GAGAL", galat.message, false);
    } finally {
        tombol.disabled = false;
        setTimeout(() => tombol.classList.remove("terkirim", "gagal"), 1800);
    }
}

async function kirimPerintah(perintah, konfirmasi) {
    if (konfirmasi && !confirm(konfirmasi)) return false;
    const pemeriksa = buatPemeriksaPerintah(perintah);
    const sudahSesuai = Boolean(pemeriksa && stateBackend && pemeriksa(stateBackend));
    const muatan = { id: Date.now().toString(36), ...perintah };
    const hasil = await mintaJson("/api/command", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(muatan),
    });
    catat(`COMMAND ${muatan.command} DITERIMA`, { dikirim: muatan, respons: hasil });
    if (sudahSesuai) {
        tampilkanStatusAksi(`Command ${muatan.command}: diterima; state sebelumnya sudah sesuai.`, "berhasil");
    } else {
        tungguKonfirmasi(`Command ${muatan.command}`, pemeriksa);
    }
    return true;
}

async function kirimApiRahasia(parameter, konfirmasi) {
    if (konfirmasi && !confirm(konfirmasi)) return false;
    const pemeriksa = buatPemeriksaRahasia(parameter);
    const sudahSesuai = Boolean(pemeriksa && stateBackend && pemeriksa(stateBackend));
    const hasil = await mintaJson(`/api/rahasia?${parameter}`);
    catat(`API RAHASIA ${parameter}`, hasil);
    if (sudahSesuai) {
        tampilkanStatusAksi(`API ${parameter}: berhasil; state sebelumnya sudah sesuai.`, "berhasil");
    } else {
        tungguKonfirmasi(`API ${parameter}`, pemeriksa);
    }
    return true;
}

function tutupKoneksiState() {
    clearTimeout(timerHubungUlang);
    if (soketState) {
        soketState.onclose = null;
        soketState.close();
        soketState = null;
    }
    if (klienMqtt) {
        klienMqtt.end(true);
        klienMqtt = null;
    }
}

function hubungkanStateLokal(versi) {
    const ip = olehId("ipLokal").value.trim();
    let soket;
    try {
        soket = new WebSocket(`ws://${ip}:${PORT_WS_ROBOT}`);
    } catch (galat) {
        ubahStatus("statusState", "Alamat state lokal tidak valid", "mati");
        catat("KONEKSI STATE LOKAL GAGAL", galat.message, false);
        return;
    }
    soketState = soket;
    ubahStatus("statusState", "Menghubungkan state lokal", "tunggu");

    soket.onopen = () => {
        if (versi !== versiKoneksi) return;
        soket.send(JSON.stringify({ aksi: "berlangganan", topik: TOPIK_STATE_LOKAL }));
        ubahStatus("statusState", "Menunggu broadcast lokal", "tunggu");
    };
    soket.onmessage = event => {
        if (versi !== versiKoneksi) return;
        try {
            const pesan = JSON.parse(event.data);
            if (pesan.aksi === "pesan" && pesan.topik === TOPIK_STATE_LOKAL) {
                terapkanState(pesan.data, "WebSocket lokal");
            } else if (!pesan.aksi && stateValid(pesan)) {
                terapkanState(pesan, "WebSocket kompatibilitas");
            }
        } catch (galat) {
            catat("STATE LOKAL RUSAK", galat.message, false);
        }
    };
    soket.onerror = () => soket.close();
    soket.onclose = () => {
        if (versi !== versiKoneksi) return;
        ubahStatus("statusState", "State lokal terputus", "mati");
        timerHubungUlang = setTimeout(() => hubungkanStateLokal(versi), 1500);
    };
}

function muatLibraryMqtt() {
    if (window.mqtt) return Promise.resolve(window.mqtt);
    if (janjiLibraryMqtt) return janjiLibraryMqtt;
    janjiLibraryMqtt = new Promise((selesai, gagal) => {
        const skrip = document.createElement("script");
        const batasWaktu = setTimeout(() => gagal(new Error("Waktu muat MQTT.js habis")), 10000);
        skrip.src = URL_LIBRARY_MQTT;
        skrip.onload = () => {
            clearTimeout(batasWaktu);
            window.mqtt ? selesai(window.mqtt) : gagal(new Error("MQTT.js tidak tersedia"));
        };
        skrip.onerror = () => {
            clearTimeout(batasWaktu);
            gagal(new Error("MQTT.js gagal dimuat"));
        };
        document.head.appendChild(skrip);
    });
    return janjiLibraryMqtt;
}

async function hubungkanStateCloud(versi) {
    ubahStatus("statusState", "Memuat MQTT cloud", "tunggu");
    try {
        const mqtt = await muatLibraryMqtt();
        if (versi !== versiKoneksi || !gunakanCloud()) return;
        const idAcak = Math.random().toString(16).slice(2, 10);
        const klien = mqtt.connect(MQTT_CONFIG.url, {
            username: MQTT_CONFIG.username,
            password: MQTT_CONFIG.password,
            clientId: `secret-${idAcak}`,
            protocolVersion: 4,
            clean: true,
            connectTimeout: 5000,
            reconnectPeriod: 3000,
            keepalive: 30,
        });
        klienMqtt = klien;
        klien.on("connect", () => {
            if (versi !== versiKoneksi) return;
            ubahStatus("statusState", "Menunggu broadcast MQTT", "tunggu");
            klien.subscribe(TOPIK_STATE_CLOUD, { qos: 0 }, galat => {
                if (galat) catat("SUBSCRIBE MQTT GAGAL", galat.message, false);
            });
        });
        klien.on("message", (topik, muatan) => {
            if (versi !== versiKoneksi || topik !== TOPIK_STATE_CLOUD) return;
            try {
                terapkanState(JSON.parse(muatan.toString()), "MQTT cloud");
            } catch (galat) {
                catat("STATE MQTT RUSAK", galat.message, false);
            }
        });
        klien.on("offline", () => {
            if (versi === versiKoneksi) ubahStatus("statusState", "MQTT cloud offline", "mati");
        });
        klien.on("error", galat => {
            if (versi === versiKoneksi) catat("MQTT GAGAL", galat.message, false);
        });
    } catch (galat) {
        janjiLibraryMqtt = null;
        if (versi === versiKoneksi) ubahStatus("statusState", galat.message, "mati");
        catat("KONEKSI STATE CLOUD GAGAL", galat.message, false);
    }
}

function hubungkanState() {
    versiKoneksi += 1;
    const versi = versiKoneksi;
    tutupKoneksiState();
    stateBackend = null;
    waktuStateTerakhir = 0;
    konfirmasiMenunggu = [];
    olehId("sumberState").textContent = "Menunggu broadcast";
    olehId("stateMentah").textContent = "Belum ada state.";
    document.querySelectorAll(".ringkasan-state strong").forEach(elemen => { elemen.textContent = "-"; });
    document.querySelectorAll("button.aktif").forEach(tombol => tombol.classList.remove("aktif"));
    if (gunakanCloud()) hubungkanStateCloud(versi);
    else hubungkanStateLokal(versi);
}

async function periksaKesehatanApi(catatHasil = true) {
    try {
        const hasil = await mintaJson("/health");
        ubahStatus("statusApi", "API tersambung", "hidup");
        if (catatHasil) catat("HEALTH", hasil);
        return hasil;
    } catch (galat) {
        ubahStatus("statusApi", "API tidak tersambung", "mati");
        throw galat;
    }
}

function perbaruiAlamatApi() {
    olehId("alamatApi").textContent = alamatDasarApi();
    ubahStatus("statusApi", "Memeriksa API", "tunggu");
    hubungkanState();
    periksaKesehatanApi(false).catch(() => {});
}

document.querySelectorAll("[data-perintah]").forEach(tombol => {
    tombol.onclick = () => jalankan(tombol, () => kirimPerintah(
        JSON.parse(tombol.dataset.perintah),
        tombol.dataset.konfirmasi,
    ));
});

document.querySelectorAll("[data-rahasia]").forEach(tombol => {
    tombol.onclick = () => jalankan(tombol, () => kirimApiRahasia(
        tombol.dataset.rahasia,
        tombol.dataset.konfirmasi,
    ));
});

document.querySelectorAll("[data-muat-foto]").forEach(tombol => {
    tombol.onclick = () => {
        const kamera = tombol.dataset.muatFoto;
        const gambar = olehId(kamera === "atas" ? "fotoAtas" : "fotoBawah");
        gambar.src = `${alamatDasarApi()}/foto/${kamera}.jpg?v=${Date.now()}`;
        gambar.onerror = () => catat(`FOTO ${kamera.toUpperCase()} GAGAL`, "Foto belum tersedia atau HTTP tidak terjangkau", false);
    };
});

olehId("formPid").onsubmit = event => {
    event.preventDefault();
    const formulir = new FormData(event.currentTarget);
    const perintah = { command: "set_pid" };
    for (const [nama, nilai] of formulir.entries()) perintah[nama] = Number(nilai);
    jalankan(event.submitter, () => kirimPerintah(perintah, "Simpan nilai PID baru?"));
};

olehId("kirimMentah").onclick = event => jalankan(event.currentTarget, async () => {
    const perintah = JSON.parse(olehId("perintahMentah").value);
    if (!perintah || Array.isArray(perintah) || typeof perintah.command !== "string") {
        throw new Error("JSON harus berupa object dan memiliki command");
    }
    return kirimPerintah(perintah, "Kirim command JSON mentah ini?");
});

olehId("periksaApi").onclick = event => jalankan(event.currentTarget, () => periksaKesehatanApi());
olehId("bersihkanLog").onclick = () => { olehId("logRespons").textContent = "Siap."; };
olehId("sumberApi").onchange = perbaruiAlamatApi;
olehId("ipLokal").onchange = perbaruiAlamatApi;

setInterval(() => {
    cekKonfirmasiState();
    if (waktuStateTerakhir && Date.now() - waktuStateTerakhir > 5000) {
        ubahStatus("statusState", "State kedaluwarsa", "mati");
    }
}, 1000);

perbaruiAlamatApi();
