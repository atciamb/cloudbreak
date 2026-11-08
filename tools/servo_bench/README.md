# Servo bench tester (Arduino UNO Q, D9)

A browser page plus an Arduino sketch for testing the Tutor's servos one at a time, without the FC. Use it to:

- centre each servo so you can set pushrod neutral;
- move each servo through the 1100–1900 µs range the FC will command (ArduPilot's default `SERVOn_MIN`/`MAX`) and check for binding;
- record which way each surface moves, which P4 needs for `SERVOn_REVERSED`.

| File | What it is |
|---|---|
| `servo_bench_gui.html` | The control page. Opens in **Chrome or Edge** and talks to the UNO Q over USB (Web Serial). Nothing to install. |
| `open_servo_bench.bat` | Opens the page in Chrome, or in Edge if Chrome isn't installed. Useful when your default browser is Firefox, which has no Web Serial. |
| `servo_bench_d9/servo_bench_d9.ino` | The UNO Q sketch: drives D9 and takes commands over USB. |
| `servo_bench_d9/src/Servo/` | The official Servo 1.3.0 library's UNO Q backend, bundled so nothing needs installing (LGPL 2.1, see its README). |

## Wiring (one servo at a time)

| Servo wire | UNO Q pin |
|---|---|
| Signal (orange / yellow / white) | **D9** |
| + (red) | **5V** (power header) |
| − (brown / black) | **GND** (power header, next to 5V) |

- **Unplug that servo's lead from the FC first.** Otherwise the UNO Q's 5V back-feeds the FC servo rail. The flight battery stays disconnected, and every power event goes through P1 (Iain).
- The servo plug and the UNO Q headers are both female, so use **3 male-to-male jumpers**.
- D9 is 3.3 V logic; hobby servos accept it.
- The servo runs off the board's USB power. One 9 g servo moving freely is fine. If the UNO Q resets or the servo stutters, the USB port is short of current: use a stronger USB-C port or supply, keep the surface free, and don't hold it against a stop.

The page has the same wiring as a diagram.

## Setup (once per computer, Arduino IDE 2)

1. Open `servo_bench_d9/servo_bench_d9.ino`.
2. **Tools › Board › Arduino UNO Q Board › Arduino UNO Q**, and pick its port. Not "Arduino Uno": that board's avrdude upload fails with `stk500_getsync`.
   If the UNO Q isn't listed, install **Arduino UNO Q Board** in Boards Manager first.
3. Servo is bundled with the sketch (`servo_bench_d9/src/Servo`), so there's nothing to install for it. Keep the whole `servo_bench_d9` folder together. If the IDE says `Arduino_RouterBridge.h` is missing, install **Arduino_RouterBridge** from Library Manager (choose "Install all").
4. Upload. The servo centres at 1500 µs right away, even before the USB link is up, so the board doubles as a centring jig.

## Using it

1. **Close the IDE's Serial Monitor**, because it holds the port.
2. Open `servo_bench_gui.html` in Chrome or Edge, or run `open_servo_bench.bat`.
3. Press **Connect UNO Q** and choose the UNO Q port. If it isn't listed, use **Other port…** and pick its COM port.
4. The status pill turns green ("Board answering") once the sketch replies. After a power-up, the board's Linux side can take up to a minute before it answers. The servo already holds centre during that time.
5. Pick the surface under test, then use the controls:

   | Control | Action |
   |---|---|
   | Slider, ±10/±50, presets | Set position |
   | **Centre** (Space) | Go to 1500 µs |
   | **Release** (R) | Stop pulses so the servo goes limp |
   | **Sweep** (S) | Automatic back-and-forth |
   | Speed setting | Board-side slew limit |
   | "Extended range" | Allows 1000–2000 µs (watch for binding) |

6. Fill in the **Results for P4** table for each surface (centred, smooth, which way the trailing edge goes at the high end, notes). Press **Copy results** and paste the table into your update or the team chat. Results are saved in the browser between visits.

**Demo** runs a simulated board, so you can try the page without hardware. Closing the page or unplugging USB leaves the servo holding its last position while the board has power.

## Commands (Serial Monitor fallback)

If the page won't connect, you can type the same commands into the IDE Serial Monitor. Set the line ending to "New Line".

| Command | Effect |
|---|---|
| `1500` or `P1500` | Go to 1500 µs (clamped to 1000–2000) |
| `C` | Centre (1500 µs) |
| `R` / `H` | Release (no pulses) / hold again |
| `S200` | Sweep 1500 ± 200 µs, 2 s period |
| `S200,3000` | Same sweep, 3 s period |
| `X` | Stop the sweep and hold where it is |
| `V1500` | Slew limit in µs per second (`V0` = jump instantly) |
| `?` | Identify + status |

Replies are `ID cloudbreak-servo-bench v1 …`, `ST us=… tgt=… mode=HOLD|SWEEP|LIMP …` and `ERR …`.

## How it works (UNO Q notes)

- The UNO Q's USB-C port goes to its Linux processor, not to the microcontroller. The sketch therefore talks to the PC through the `Monitor` object from **Arduino_RouterBridge**. On this board `Serial` is the hardware UART on D0/D1.
- `Monitor.begin()` waits until Linux has booted. The sketch attaches the servo before calling it, which is why centring starts immediately.
- Pulses come from the bundled **Servo** library's hardware-timer interrupt (4 µs steps, 50 Hz), so they keep running while the sketch waits on USB traffic. **Release** detaches the servo with interrupts off, so the library's interrupt never sees a half-freed slot.
- The page clamps to 1100–1900 µs (or 1000–2000 µs in extended mode). The sketch also clamps to 1000–2000 µs whatever it's sent.

## Troubleshooting

| Symptom | Fix |
|---|---|
| Upload error `avrdude … stk500_getsync` | Wrong board selected: choose Arduino UNO Q. |
| `Arduino_RouterBridge.h: No such file` | Install Arduino_RouterBridge from Library Manager. |
| `Please update the Arduino_RouterBridge library` | Update it in Library Manager. |
| `Servo.h: No such file or directory` | The sketch was copied without its `src/` folder. Copy the whole `servo_bench_d9` folder. |
| "Couldn't open the port" | Close the IDE Serial Monitor (or any other app using the port), then retry. |
| Port open but the board stays quiet | Wait about a minute after power-up. Check the sketch uploaded. Try **Other port…** and pick COM3 directly. |
| Page says the browser can't open serial ports | Open it in Chrome or Edge, or run `open_servo_bench.bat`. |
| Board resets when the servo moves | USB current limit: use a stronger USB-C port or supply, free the surface, and test one servo at a time. |
