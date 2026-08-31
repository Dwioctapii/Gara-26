#include <Servo.h>

Servo steerServo;
uint8_t buf[5];
int bufIdx = 0;

void setup() {
  Serial.begin(115200);
  steerServo.attach(9);          // ganti pin sesuai wiring
  steerServo.writeMicroseconds(1500);
}

void loop() {
  while (Serial.available()) {
    uint8_t b = Serial.read();
    if (bufIdx == 0 && b != 0xAA) continue;  // tunggu header
    buf[bufIdx++] = b;
    if (bufIdx == 5) {
      bufIdx = 0;
      if ((buf[1] ^ buf[2] ^ buf[3]) != buf[4]) continue; // checksum gagal
      
      int pwm      = buf[1] | (buf[2] << 8);
      uint8_t mode = buf[3]; // 0=MANUAL 1=AUTO 2=HOLD 0xFF=DISCONNECT
      
      int finalPwm = constrain(pwm, 1100, 1900);
      steerServo.writeMicroseconds(finalPwm);

      // Print ringkas: PWM dan Mode
      Serial.print("PWM: ");
      Serial.print(finalPwm);
      Serial.print(" | Mode: ");
      Serial.println(mode);
    }
  }
}
