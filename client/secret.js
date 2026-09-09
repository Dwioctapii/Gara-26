const DOMAIN_ROBOT = "robot.neiaozora.my.id";
const PORT_HTTP_ROBOT = 8766;
const PILIHAN_OTOMATIS = "otomatis";

const olehId = id => document.getElementById(id);

function alamatDasarApi() {
    const pilihan = olehId("sumberApi").value;
    const gunakanCloud = pilihan === "cloud"
        || (pilihan === PILIHAN_OTOMATIS && location.protocol === "https:");
    if (gunakanCloud) return `https://${DOMAIN_ROBOT}`;
    return `http://${olehId("ipLokal").value.trim()}:${PORT_HTTP_ROBOT}`;
}

function perbaruiAlamatApi() {
    olehId("alamatApi").textContent = alamatDasarApi();
    olehId("statusApi").textContent = "Belum diperiksa";
    olehId("statusApi").className = "status mati";
}

function catat(judul, data, berhasil = true) {
    const waktu = new Date().toLocaleTimeString();
    const isi = typeof data === "string" ? data : JSON.stringify(data, null, 2);
    const log = olehId("logRespons");
    log.textContent = `[${waktu}] ${judul}\n${isi}\n\n${log.textContent}`;
    log.style.color = berhasil ? "#a7f3d0" : "#fecaca";
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
    if (!respons.ok || isi.ok === false) {
        throw new Error(isi.error || `HTTP ${respons.status}`);
    }
    return isi;
}

async function jalankan(tombol, pekerjaan) {
    tombol.disabled = true;
    try {
        await pekerjaan();
    } catch (galat) {
        catat("GAGAL", galat.message, false);
    } finally {
        tombol.disabled = false;
    }
}

async function kirimPerintah(perintah, konfirmasi) {
    if (konfirmasi && !confirm(konfirmasi)) return;
    const muatan = { id: Date.now().toString(36), ...perintah };
    const hasil = await mintaJson("/api/command", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(muatan),
    });
    catat(`COMMAND ${muatan.command}`, { dikirim: muatan, respons: hasil });
}

async function kirimApiRahasia(parameter, konfirmasi) {
    if (konfirmasi && !confirm(konfirmasi)) return;
    const hasil = await mintaJson(`/api/rahasia?${parameter}`);
    catat(`API RAHASIA ${parameter}`, hasil);
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
    const tombol = event.submitter;
    const formulir = new FormData(event.currentTarget);
    const perintah = { command: "set_pid" };
    for (const [nama, nilai] of formulir.entries()) perintah[nama] = Number(nilai);
    jalankan(tombol, () => kirimPerintah(perintah, "Simpan nilai PID baru?"));
};

olehId("kirimMentah").onclick = event => jalankan(event.currentTarget, async () => {
    const perintah = JSON.parse(olehId("perintahMentah").value);
    if (!perintah || Array.isArray(perintah) || typeof perintah.command !== "string") {
        throw new Error("JSON harus berupa object dan memiliki command");
    }
    await kirimPerintah(perintah, "Kirim command JSON mentah ini?");
});

olehId("periksaApi").onclick = event => jalankan(event.currentTarget, async () => {
    const hasil = await mintaJson("/health");
    olehId("statusApi").textContent = "API tersambung";
    olehId("statusApi").className = "status hidup";
    catat("HEALTH", hasil);
});

olehId("bersihkanLog").onclick = () => {
    olehId("logRespons").textContent = "Siap.";
};
olehId("sumberApi").onchange = perbaruiAlamatApi;
olehId("ipLokal").onchange = perbaruiAlamatApi;
perbaruiAlamatApi();
