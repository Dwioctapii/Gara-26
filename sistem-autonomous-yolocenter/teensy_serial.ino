#include <Servo.h>

// ─────────────────────────────────────────────────────────────────
// Protokol paket serial dari Raspberry Pi / PC (6 byte):
//   [0] 0xAA          — sync header
//   [1] PWM low byte  — servo_pwm & 0xFF
//   [2] PWM high byte — servo_pwm >> 8
//   [3] mode byte     — 0=MANUAL, 1=AUTO, 2=HOLD, 0xFF=DISCONNECT
//   [4] detect byte   — 0x01 = buoy terdeteksi, 0x00 = tidak ada buoy
//   [5] XOR checksum  — byte[1] ^ byte[2] ^ byte[3] ^ byte[4]
// ─────────────────────────────────────────────────────────────────

Servo steerServo;

uint8_t buf[6];      // buffer paket 6 byte
int     bufIdx = 0;

// Status terakhir yang diterima (untuk dipakai di logika lain)
int     lastPwm      = 1500;
uint8_t lastMode     = 0xFF;   // 0xFF = DISCONNECT (nilai awal aman)
bool    buoyDetected = false;

// ── Pin output ────────────────────────────────────────────────────
const int PIN_SERVO   = 9;    // ganti sesuai wiring servo kemudi
const int PIN_LED_DET = 13;   // LED indikator deteksi buoy (onboard LED Teensy)

void setup() {
  Serial.begin(115200);

  steerServo.attach(PIN_SERVO);
  steerServo.writeMicroseconds(1500);   // posisi netral saat startup

  pinMode(PIN_LED_DET, OUTPUT);
  digitalWrite(PIN_LED_DET, LOW);

  Serial.println("[TEENSY] Siap menerima paket 6-byte.");
}

void loop() {
  // ── Parsing paket serial ────────────────────────────────────────
  while (Serial.available()) {
    uint8_t b = Serial.read();

    // Tunggu sync header 0xAA di posisi pertama
    if (bufIdx == 0 && b != 0xAA) continue;

    buf[bufIdx++] = b;

    if (bufIdx == 6) {
      bufIdx = 0;   // reset buffer untuk paket berikutnya

      // Verifikasi checksum: XOR dari 4 payload byte harus sama dengan byte[5]
      uint8_t csum = buf[1] ^ buf[2] ^ buf[3] ^ buf[4];
      if (csum != buf[5]) {
        // Checksum gagal → abaikan paket (data korup / noise)
        continue;
      }

      // ── Ekstrak nilai dari paket ─────────────────────────────────
      int     pwm    = (int)buf[1] | ((int)buf[2] << 8);
      uint8_t mode   = buf[3];
      bool    detect = (buf[4] == 0x01);

      // Simpan ke variabel global untuk dipakai fungsi lain
      lastPwm      = pwm;
      lastMode     = mode;
      buoyDetected = detect;

      // ── Aksi berdasarkan mode ────────────────────────────────────
      if (mode == 0xFF) {
        // DISCONNECT: kembalikan servo ke netral sebagai fallback aman
        steerServo.writeMicroseconds(1500);
      } else {
        // MANUAL / AUTO / HOLD: terapkan PWM dari Pi
        steerServo.writeMicroseconds(constrain(pwm, 1100, 1900));
      }

      // ── Indikator LED deteksi buoy ───────────────────────────────
      // LED ON  = buoy terdeteksi (detect byte = 0x01)
      // LED OFF = tidak ada buoy  (detect byte = 0x00)
      digitalWrite(PIN_LED_DET, detect ? HIGH : LOW);
    }
  }

  // ── Area logika tambahan di luar parsing serial ─────────────────
  // Gunakan variabel lastPwm, lastMode, buoyDetected di sini.
}