/*
  Cloudbreak servo bench v2: Arduino UNO Q, ONE servo on D9.
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
    Library Manager: install "Arduino_RouterBridge" if the IDE says it's missing.
    No Servo library needed (see below).

  HOW THE PULSES ARE MADE (hardware, no interrupts)
    D9 is PB8, wired inside the chip to timer TIM4 channel 3. analogWrite()
    lets the core route the pin to that timer (it runs it at 500 Hz). The
    sketch then retimes the timer to 1 us ticks and 20 ms frames, so the
    hardware produces every servo pulse exactly, whatever the CPU is doing.
    (v1 used the Servo library, whose UNO Q version toggles the pin from a
    250 kHz interrupt; with USB traffic it fell behind and the servo buzzed.)

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
    M                 self-test: read D9 back and measure the real pulse and frame
    ?                 identify + status

  REPLIES
    ID cloudbreak-servo-bench v2 pin=D9 pwm=hw ch=<n> tick=<Hz> range=1000-2000
    ST us=<output> tgt=<target> mode=<HOLD|SWEEP|LIMP> slew=<us/s> amp=<us> per=<ms> up=<s>
    MEAS pin=<ok|no-pulses|stuck-high> pulse=<us> set=<us> frame=<us> clk=<Hz> psc=<n> arr=<n>
    ERR <reason>

  At power-up the servo is centred straight away, before the Linux side has
  booted (that can take a minute), so the board also works as a centring jig.
*/

#include <Arduino_RouterBridge.h>
#include <math.h>

#if !defined(ARDUINO_ARCH_ZEPHYR)
#error "Wrong board: choose Tools > Board > Arduino UNO Q Board > Arduino UNO Q (not the classic Arduino Uno)."
#endif

const int SERVO_PIN     = 9;      // D9
const int HARD_MIN_US   = 1000;   // never output outside this window
const int HARD_MAX_US   = 2000;
const int CENTER_US     = 1500;
const int SWEEP_MAX_AMP = 500;
const uint32_t FRAME_US = 20000;  // 50 Hz servo frame

const unsigned long POLL_MS   = 20;    // how often to ask Monitor for new input
const unsigned long STEP_MS   = 5;     // slew / sweep update interval
const unsigned long STATUS_MS = 100;   // fastest status rate while moving
const unsigned long BEAT_MS   = 1000;  // heartbeat status when idle

// ---------------------------------------------------------------------------
// Hardware PWM on the pin's timer channel.
// These tables are built from the board's devicetree exactly the way the core
// builds its analogWrite() tables, so the index for D9 matches the core's.
// ---------------------------------------------------------------------------
#define CB_PWM_PIN(n, p, i)                                                        \
  DIGITAL_PIN_GPIOS_FIND_PIN(DT_REG_ADDR(DT_PHANDLE_BY_IDX(DT_PATH(zephyr_user), p, i)), \
                             DT_PHA_BY_IDX(DT_PATH(zephyr_user), p, i, pin)),
#define CB_PWM_PERIOD_NS(n, p, i) DT_PWMS_PERIOD_BY_IDX(n, i),
#define CB_PWM_CHANNEL(n, p, i)   DT_PWMS_CHANNEL_BY_IDX(n, i),
#define CB_PWM_TIMER(n, p, i)     DT_REG_ADDR(DT_PARENT(DT_PWMS_CTLR_BY_IDX(n, i))),

static const pin_size_t kPwmPins[]     = { DT_FOREACH_PROP_ELEM(DT_PATH(zephyr_user), pwm_pin_gpios, CB_PWM_PIN) };
static const uint32_t   kPwmPeriodNs[] = { DT_FOREACH_PROP_ELEM(DT_PATH(zephyr_user), pwms, CB_PWM_PERIOD_NS) };
static const uint32_t   kPwmChannel[]  = { DT_FOREACH_PROP_ELEM(DT_PATH(zephyr_user), pwms, CB_PWM_CHANNEL) };
static const uintptr_t  kPwmTimer[]    = { DT_FOREACH_PROP_ELEM(DT_PATH(zephyr_user), pwms, CB_PWM_TIMER) };

TIM_TypeDef       *g_tim        = nullptr;
volatile uint32_t *g_ccr        = nullptr;   // compare register = pulse length in ticks
uint32_t           g_channel    = 0;
uint32_t           g_timClkHz   = 0;
uint32_t           g_tickHz     = 0;
uint32_t           g_frameTicks = 0;
bool               g_pwmOk      = false;
const char        *g_pwmErr     = "not started";

uint32_t usToTicks(uint32_t us) { return (uint32_t)(((uint64_t)us * g_tickHz + 500000ULL) / 1000000ULL); }
uint32_t ticksToUs(uint32_t t)  { return g_tickHz ? (uint32_t)(((uint64_t)t * 1000000ULL + g_tickHz / 2) / g_tickHz) : 0; }

bool pwmInit() {
  int idx = -1;
  for (size_t i = 0; i < sizeof(kPwmPins) / sizeof(kPwmPins[0]); i++) {
    if (kPwmPins[i] == SERVO_PIN) { idx = (int)i; break; }
  }
  if (idx < 0) { g_pwmErr = "D9 has no PWM channel in this core"; return false; }

  analogWrite(SERVO_PIN, 0);   // core: route D9 to its timer channel and start it (output low)

  g_tim     = (TIM_TypeDef *)kPwmTimer[idx];
  g_channel = kPwmChannel[idx];
  if (g_channel < 1 || g_channel > 4) { g_pwmErr = "unexpected PWM channel"; return false; }
  g_ccr = &g_tim->CCR1 + (g_channel - 1);

  // The core set ARR+1 counts per devicetree period, which gives the timer clock.
  uint64_t countsPerSec = (uint64_t)(g_tim->ARR + 1) * 1000000000ULL / kPwmPeriodNs[idx];
  g_timClkHz = (uint32_t)(countsPerSec * (g_tim->PSC + 1));
  uint32_t div = (g_timClkHz + 500000UL) / 1000000UL;   // prescaler for ~1 MHz ticks
  if (div < 1 || div > 65536) { g_pwmErr = "timer clock out of range"; return false; }
  g_tickHz     = g_timClkHz / div;
  g_frameTicks = usToTicks(FRAME_US);
  if (g_frameTicks < 1000 || g_frameTicks > 65536) { g_pwmErr = "frame does not fit the timer"; return false; }

  g_tim->CR1 &= ~TIM_CR1_CEN;
  *g_ccr      = 0;
  g_tim->PSC  = div - 1;
  g_tim->ARR  = g_frameTicks - 1;
  g_tim->CNT  = 0;
  g_tim->EGR  = TIM_EGR_UG;      // load the new prescaler and period now
  g_tim->CR1 |= TIM_CR1_CEN;

  g_pwmErr = "";
  return true;
}

// New values take effect at the next frame (compare preload), so changes are glitch-free.
void pwmWriteUs(int us) { if (g_pwmOk) *g_ccr = usToTicks((uint32_t)us); }
void pwmOff()           { if (g_pwmOk) *g_ccr = 0; }

// ---------------------------------------------------------------------------

enum BenchMode { MODE_HOLD, MODE_SWEEP, MODE_LIMP };

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
  if (g_pwmOk) {
    sendLine("ID cloudbreak-servo-bench v2 pin=D9 pwm=hw ch=" + String(g_channel) +
             " tick=" + String(g_tickHz) + "Hz range=" + String(HARD_MIN_US) + "-" + String(HARD_MAX_US));
  } else {
    sendLine("ID cloudbreak-servo-bench v2 pin=D9 pwm=FAILED range=" + String(HARD_MIN_US) + "-" + String(HARD_MAX_US));
    sendLine(String("ERR hardware PWM setup failed: ") + g_pwmErr);
  }
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
void startPulses() {
  g_writtenUs = clampUs(roundToInt(g_outUs));
  pwmWriteUs(g_writtenUs);
}

void releaseServo() {
  if (g_mode == MODE_LIMP) return;
  pwmOff();                      // compare = 0: D9 stays low, no pulses
  g_mode = MODE_LIMP;
}

// Leave LIMP, snapping straight to startUs (the servo's real position is unknown).
void ensurePulses(int startUs) {
  if (g_mode != MODE_LIMP) return;
  g_outUs = startUs;
  startPulses();
  g_mode = MODE_HOLD;
}

void goTo(long us) {
  int t = clampUs(us);
  ensurePulses(t);
  g_mode     = MODE_HOLD;
  g_targetUs = t;
}

// Read D9 back while the timer drives it: frame length against micros(), and the
// pulse length from the timer count at the falling edge. Blocks for up to ~0.5 s.
void selfTest() {
  if (!g_pwmOk) { sendLine(String("ERR self-test: hardware PWM not running: ") + g_pwmErr); return; }

  // 1) frame length: time 10 counter wraps
  uint32_t last = g_tim->CNT, wraps = 0, t1 = 0, t2 = 0;
  unsigned long guard = millis();
  while (wraps < 11 && millis() - guard < 400) {
    uint32_t c = g_tim->CNT;
    if (c < last) {
      if (wraps == 0) t1 = micros();
      wraps++;
      if (wraps == 11) t2 = micros();
    }
    last = c;
  }
  long frameUs = (wraps == 11) ? (long)((t2 - t1) / 10) : -1;

  // 2) the pin itself: wait for low, then high, then read the count at the fall
  enum { WAIT_LOW, WAIT_HIGH, WAIT_FALL } st = WAIT_LOW;
  bool sawHigh = false, sawLow = false;
  long pulseUs = -1;
  guard = millis();
  while (millis() - guard < 100) {
    bool hi = digitalRead(SERVO_PIN) == HIGH;
    if (hi) sawHigh = true; else sawLow = true;
    if (st == WAIT_LOW && !hi) st = WAIT_HIGH;
    else if (st == WAIT_HIGH && hi) st = WAIT_FALL;
    else if (st == WAIT_FALL && !hi) { pulseUs = (long)ticksToUs(g_tim->CNT); break; }
  }
  const char *pin = pulseUs >= 0 ? "ok" : (sawHigh && !sawLow ? "stuck-high" : "no-pulses");

  sendLine(String("MEAS pin=") + pin +
           " pulse=" + String(pulseUs) + "us" +
           " set=" + String(g_mode == MODE_LIMP ? 0 : g_writtenUs) + "us" +
           " frame=" + String(frameUs) + "us" +
           " clk=" + String(g_timClkHz) +
           " psc=" + String((uint32_t)g_tim->PSC) +
           " arr=" + String((uint32_t)g_tim->ARR));
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
    case 'M':
      selfTest();
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
    pwmWriteUs(us);
    g_writtenUs   = us;
    g_statusDirty = true;
  }
}

void blinkLed(unsigned long now) {
  unsigned long half = !g_pwmOk ? 60 : (g_mode == MODE_SWEEP) ? 125 : (g_mode == MODE_LIMP ? 1000 : 500);
  if (now - g_lastLed >= half) {
    g_lastLed = now;
    g_led = !g_led;
    digitalWrite(LED_BUILTIN, g_led ? HIGH : LOW);
  }
}

void setup() {
  pinMode(LED_BUILTIN, OUTPUT);
  digitalWrite(LED_BUILTIN, HIGH);

  g_pwmOk = pwmInit();           // D9 on its hardware timer: 1 us ticks, 20 ms frames
  startPulses();                 // centre pulses start now

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
