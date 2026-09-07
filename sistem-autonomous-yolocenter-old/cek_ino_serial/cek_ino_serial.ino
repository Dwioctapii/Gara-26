#include <Servo.h>

const uint8_t in_PWM[6] = {14, 15, 38, 39, 40, 41};
const uint8_t escPin[4] = {6, 7, 4, 8};
const uint8_t servoPin[2] = {2, 3};

Servo esc[4];
Servo servo[2];

volatile uint32_t riseTime[6] = {0};

volatile uint16_t pwmValue[6] = {
  1500, 1500, 1500,
  1500, 1500, 1500
};

uint8_t buf[5];
uint8_t bufIdx = 0;

uint8_t mode = 0;
uint16_t pcPwm = 1500;

uint32_t lastPcPacket = 0;

const uint32_t PC_TIMEOUT = 500;

int limitPWM(int pwm) {
  return constrain(pwm, 1000, 1900);
}

void pwmISR0() {
  uint32_t now = micros();

  if (digitalReadFast(14))
    riseTime[0] = now;
  else
    pwmValue[0] = now - riseTime[0];
}

void pwmISR1() {
  uint32_t now = micros();

  if (digitalReadFast(15))
    riseTime[1] = now;
  else
    pwmValue[1] = now - riseTime[1];
}

void pwmISR2() {
  uint32_t now = micros();

  if (digitalReadFast(38))
    riseTime[2] = now;
  else
    pwmValue[2] = now - riseTime[2];
}

void pwmISR3() {
  uint32_t now = micros();

  if (digitalReadFast(39))
    riseTime[3] = now;
  else
    pwmValue[3] = now - riseTime[3];
}

void pwmISR4() {
  uint32_t now = micros();

  if (digitalReadFast(40))
    riseTime[4] = now;
  else
    pwmValue[4] = now - riseTime[4];
}

void pwmISR5() {
  uint32_t now = micros();

  if (digitalReadFast(41))
    riseTime[5] = now;
  else
    pwmValue[5] = now - riseTime[5];
}

void readPC() {

  while (Serial.available()) {

    uint8_t b = Serial.read();

    if (bufIdx == 0 && b != 0xAA)
      continue;

    buf[bufIdx++] = b;

    if (bufIdx == 5) {

      bufIdx = 0;

      uint8_t checksum =
        buf[1] ^
        buf[2] ^
        buf[3];

      if (checksum != buf[4])
        continue;

      uint16_t newPwm =
        buf[1] |
        ((uint16_t)buf[2] << 8);

      uint8_t newMode = buf[3];

      if (newMode != 0 &&
          newMode != 1 &&
          newMode != 2 &&
          newMode != 0xFF)
        continue;

      pcPwm = limitPWM(newPwm);
      mode = newMode;

      lastPcPacket = millis();
    }
  }
}

void setup() {

  Serial.begin(115200);

  for (uint8_t i = 0; i < 6; i++)
    pinMode(in_PWM[i], INPUT);

  attachInterrupt(digitalPinToInterrupt(14), pwmISR0, CHANGE);
  attachInterrupt(digitalPinToInterrupt(15), pwmISR1, CHANGE);
  attachInterrupt(digitalPinToInterrupt(38), pwmISR2, CHANGE);
  attachInterrupt(digitalPinToInterrupt(39), pwmISR3, CHANGE);
  attachInterrupt(digitalPinToInterrupt(40), pwmISR4, CHANGE);
  attachInterrupt(digitalPinToInterrupt(41), pwmISR5, CHANGE);

  for (uint8_t i = 0; i < 4; i++) {
    esc[i].attach( escPin[i], 1000, 2000 );
    esc[i].writeMicroseconds(1500);
  }

  for (uint8_t i = 0; i < 2; i++) {
    servo[i].attach( servoPin[i], 1000, 1900 );
    servo[i].writeMicroseconds(1500);
  }

  delay(4000);
}

void loop() {
  uint16_t pwm[6];
  noInterrupts();

  for (uint8_t i = 0; i < 6; i++)
    pwm[i] = pwmValue[i];
  interrupts();

  readPC();

  if (millis() - lastPcPacket > PC_TIMEOUT) {
    mode = 0;
    pcPwm = 1500;
  }

  int escOut0 = limitPWM(pwm[0]);
  int escOut1 = limitPWM(pwm[1]);
  int escOut2 = limitPWM(pwm[5]);
  int escOut3 = limitPWM(pwm[5]);

  int servoOut0 = limitPWM(pwm[2]);
  int servoOut1 = limitPWM(pwm[3]);

  if (mode == 0) {

    servoOut0 = limitPWM(pwm[2]);
    servoOut1 = limitPWM(pwm[3]);
  }

  else if (mode == 1) {
    servoOut0 = limitPWM((pwm[2] + pcPwm) / 2);
    servoOut1 = limitPWM((pwm[3] + pcPwm) / 2);
    escOut2 = 1500;
    escOut3 = 1500; 
  }

  else if (mode == 2) {
    servoOut0 = servo[0].readMicroseconds();
    servoOut1 = servo[1].readMicroseconds();
  }

  else if (mode == 0xFF) {
    escOut0 = 1500;
    escOut1 = 1500;
    escOut2 = 1500;
    escOut3 = 1500;

    servoOut0 = 1500;
    servoOut1 = 1500;
  }

  esc[0].writeMicroseconds(escOut0);
  esc[1].writeMicroseconds(escOut1);
  esc[2].writeMicroseconds(escOut2);
  esc[3].writeMicroseconds(escOut3);

  servo[0].writeMicroseconds(servoOut0);
  servo[1].writeMicroseconds(servoOut1);

  Serial.print("CH1:"); Serial.print(pwm[0]);
  Serial.print(" CH2:"); Serial.print(pwm[1]);
  Serial.print(" CH3:"); Serial.print(pwm[2]);
  Serial.print(" CH4:"); Serial.print(pwm[3]);
  Serial.print(" CH5:"); Serial.print(pwm[4]);
  Serial.print(" CH6:"); Serial.print(pwm[5]);
  Serial.print(" PC:"); Serial.print(pcPwm);
  Serial.print(" S1:"); Serial.print(servoOut0);
  Serial.print(" S2:"); Serial.print(servoOut1);
  Serial.print(" MODE:"); Serial.println(mode);

  delay(10);
}
