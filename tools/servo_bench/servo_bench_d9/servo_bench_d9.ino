/*
  Cloudbreak servo bench: Arduino UNO Q, ONE servo on D9.
  Drive it from tools/servo_bench/servo_bench_gui.html in Chrome or Edge (COM3),
  or type the commands below into the Arduino IDE Serial Monitor.

  WIRING (one servo at a time; unplug that servo's lead from the FC first)
    servo signal  (orange / yellow / white)  ->  D9
    servo +5V     (red)                      ->  5V   (power header)
    servo ground  (brown / black)            ->  GND  (power header, next to 5V)
  The servo plug and the UNO Q headers are both female: use 3 male-to-male jumpers.
  D9 outputs 3.3 V logic, which hobby servos accept.

  BEFORE UPLOADING (Arduino IDE 2)
    Tools > Board > Arduino UNO Q Board > Arduino UNO Q   (NOT "Arduino Uno")
    Library Manager: install "Arduino_RouterBridge" if the IDE says it's missing
    Servo is bundled in src/Servo (official Servo 1.3.0, UNO Q backend): nothing to install

  WHY Monitor AND NOT Serial
    On the UNO Q the USB-C port goes to the Linux side. Text to and from the
    PC travels through the Arduino_RouterBridge "Monitor" object. Serial is
    the hardware UART on pins D0/D1.

  COMMANDS (one per line, case-insensitive; Serial Monitor line ending "New Line")
    1500  or  P1500   go to 1500 us (clamped to 1000..2000)
    C                 centre (1500 us)
    R                 release: stop pulses so the servo goes limp
    H                 hold: resume pulses at the last position
    S200              sweep 1500 +/- 200 us, 2 s period  (S200,3000 = 3 s period)
    X                 stop the sweep and hold where it is
    V1500             slew limit in us per second (V0 = jump instantly)
    ?                 identify + status

  REPLIES
    ID cloudbreak-servo-bench v1 pin=D9 range=1000-2000
    ST us=<output> tgt=<target> mode=<HOLD|SWEEP|LIMP> slew=<us/s> amp=<us> per=<ms> up=<s>
    ERR <reason>

  At power-up the servo is centred straight away, before the Linux side has
  booted (that can take a minute), so the board also works as a centring jig.
*/

#include <Arduino_RouterBridge.h>
#include "src/Servo/Servo.h"   // bundled Servo 1.3.0, see src/Servo/README.md
#include <math.h>

#if !defined(ARDUINO_ARCH_ZEPHYR)
#error "Wrong board: choose Tools > Board > Arduino UNO Q Board > Arduino UNO Q (not the classic Arduino Uno)."
#endif

const int SERVO_PIN     = 9;      // D9
const int HARD_MIN_US   = 1000;   // never output outside this window
const int HARD_MAX_US   = 2000;
const int CENTER_US     = 1500;
const int SWEEP_MAX_AMP = 500;

const unsigned long POLL_MS   = 20;    // how often to ask Monitor for new input
const unsigned long STEP_MS   = 5;     // slew / sweep update interval
const unsigned long STATUS_MS = 100;   // fastest status rate while moving
const unsigned long BEAT_MS   = 1000;  // heartbeat status when idle

enum BenchMode { MODE_HOLD, MODE_SWEEP, MODE_LIMP };

// Built inside setup(), after all static objects exist.
Servo &benchServo() {
  static Servo s;
  return s;
}

BenchMode     g_mode        = MODE_HOLD;
int           g_targetUs    = CENTER_US;
float         g_outUs       = CENTER_US;
int           g_writtenUs   = CENTER_US;
long          g_slewUsPerS  = 1500;
int           g_sweepAmp    = 200;
unsigned long g_sweepPerMs  = 2000;
unsigned long g_sweepStart  = 0;

String        g_rx;
bool          g_statusDirty = true;
unsigned long g_lastPoll = 0, g_lastStep = 0, g_lastStatus = 0, g_lastLed = 0;
bool          g_led = false;

int roundToInt(float x) { return (int)(x >= 0 ? x + 0.5f : x - 0.5f); }

int clampUs(long us) {
  if (us < HARD_MIN_US) return HARD_MIN_US;
  if (us > HARD_MAX_US) return HARD_MAX_US;
  return (int)us;
}

const char *modeName() {
  switch (g_mode) {
    case MODE_SWEEP: return "SWEEP";
    case MODE_LIMP:  return "LIMP";
    default:         return "HOLD";
  }
}

void sendLine(const String &line) {
  Monitor.print(line + "\n");   // one RPC per line
}

void sendId() {
  sendLine("ID cloudbreak-servo-bench v1 pin=D9 range=" + String(HARD_MIN_US) + "-" + String(HARD_MAX_US));
}

void sendStatus() {
  sendLine("ST us=" + String(g_writtenUs) +
           " tgt=" + String(g_targetUs) +
           " mode=" + modeName() +
           " slew=" + String(g_slewUsPerS) +
           " amp=" + String(g_sweepAmp) +
           " per=" + String(g_sweepPerMs) +
           " up=" + String(millis() / 1000));
  g_lastStatus  = millis();
  g_statusDirty = false;
}

// Start pulses at g_outUs.
void attachServo() {
  benchServo().attach(SERVO_PIN, HARD_MIN_US, HARD_MAX_US);
  g_writtenUs = clampUs(roundToInt(g_outUs));
  benchServo().writeMicroseconds(g_writtenUs);
}

// Stop pulses. The library's timer interrupt walks its servo table, so detach
// with interrupts off to keep it from touching a slot while it is freed.
void releaseServo() {
  if (g_mode == MODE_LIMP) return;
  noInterrupts();
  benchServo().detach();
  interrupts();
  digitalWrite(SERVO_PIN, LOW);
  g_mode = MODE_LIMP;
}

// Leave LIMP, snapping straight to startUs (the servo's real position is unknown).
void ensurePulses(int startUs) {
  if (g_mode != MODE_LIMP) return;
  g_outUs = startUs;
  attachServo();
  g_mode = MODE_HOLD;
}

void goTo(long us) {
  int t = clampUs(us);
  ensurePulses(t);
  g_mode     = MODE_HOLD;
  g_targetUs = t;
}

void handleLine(String s) {
  s.trim();
  if (s.length() == 0) return;

  char c = toupper(s.charAt(0));
  String arg = s.substring(1);
  arg.trim();
  if (isDigit(c)) {        // a bare number is a position
    c   = 'P';
    arg = s;
  }

  switch (c) {
    case 'P': {
      long v = arg.toInt();
      if (v <= 0) { sendLine("ERR P needs a number, e.g. P1500"); return; }
      goTo(v);
      break;
    }
    case 'C':
      goTo(CENTER_US);
      break;
    case 'R':
      releaseServo();
      break;
    case 'H':
      ensurePulses(clampUs(roundToInt(g_outUs)));
      break;
    case 'S': {
      int comma = arg.indexOf(',');
      long a = (comma >= 0 ? arg.substring(0, comma) : arg).toInt();
      long p = (comma >= 0 ? arg.substring(comma + 1).toInt() : (long)g_sweepPerMs);
      if (a > 0) g_sweepAmp = constrain(a, 10, SWEEP_MAX_AMP);
      if (p > 0) g_sweepPerMs = constrain(p, 500, 20000);
      ensurePulses(CENTER_US);
      g_mode       = MODE_SWEEP;
      g_sweepStart = millis();
      break;
    }
    case 'X':
      if (g_mode == MODE_SWEEP) {
        g_targetUs = clampUs(roundToInt(g_outUs));
        g_mode     = MODE_HOLD;
      }
      break;
    case 'V':
      g_slewUsPerS = constrain(arg.toInt(), 0, 20000);
      break;
    case '?':
      sendId();
      break;
    default:
      sendLine("ERR unknown command: " + s);
      return;
  }
  sendStatus();
}

void pollInput() {
  int n = Monitor.available();          // one RPC; fills the local buffer
  for (int i = 0; i < n; i++) {
    int ch = Monitor.read();            // local buffer only
    if (ch < 0) break;
    if (ch == '\n' || ch == '\r') {
      if (g_rx.length()) handleLine(g_rx);
      g_rx = "";
    } else if (g_rx.length() < 48) {
      g_rx += (char)ch;
    } else {
      g_rx = "";                        // runaway line: drop it
    }
  }
}

void stepOutput(unsigned long now) {
  float dt = (now - g_lastStep) / 1000.0f;
  g_lastStep = now;
  if (g_mode == MODE_LIMP) return;

  if (g_mode == MODE_SWEEP) {
    float phase = (float)((now - g_sweepStart) % g_sweepPerMs) / (float)g_sweepPerMs;
    g_targetUs = clampUs(CENTER_US + roundToInt(g_sweepAmp * sinf(2.0f * (float)PI * phase)));
  }

  if (g_slewUsPerS <= 0) {
    g_outUs = g_targetUs;
  } else {
    float maxStep = g_slewUsPerS * dt;
    float d = g_targetUs - g_outUs;
    if (d > maxStep) d = maxStep;
    if (d < -maxStep) d = -maxStep;
    g_outUs += d;
  }

  int us = clampUs(roundToInt(g_outUs));
  if (us != g_writtenUs) {
    benchServo().writeMicroseconds(us);
    g_writtenUs   = us;
    g_statusDirty = true;
  }
}

void blinkLed(unsigned long now) {
  unsigned long half = (g_mode == MODE_SWEEP) ? 125 : (g_mode == MODE_LIMP ? 1000 : 500);
  if (now - g_lastLed >= half) {
    g_lastLed = now;
    g_led = !g_led;
    digitalWrite(LED_BUILTIN, g_led ? HIGH : LOW);
  }
}

void setup() {
  pinMode(LED_BUILTIN, OUTPUT);
  digitalWrite(LED_BUILTIN, HIGH);
  pinMode(SERVO_PIN, OUTPUT);
  digitalWrite(SERVO_PIN, LOW);

  attachServo();                 // centre pulses start now

  // Waits until the Linux side answers (up to ~1 min after power-up).
  // The servo keeps centring meanwhile.
  Monitor.begin();

  g_lastStep = g_lastPoll = g_lastStatus = g_lastLed = millis();
  sendId();
  sendStatus();
}

void loop() {
  unsigned long now = millis();

  if (now - g_lastStep >= STEP_MS) stepOutput(now);

  if (now - g_lastPoll >= POLL_MS) {
    g_lastPoll = now;
    pollInput();
  }

  now = millis();
  if ((g_statusDirty && now - g_lastStatus >= STATUS_MS) || now - g_lastStatus >= BEAT_MS) {
    sendStatus();
  }

  blinkLed(now);
}
